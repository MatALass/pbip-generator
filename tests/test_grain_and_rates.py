"""Rates averaged instead of summed, grain of fact tables, model diagram, DAX table columns."""

from __future__ import annotations

from pathlib import Path

import pytest

from pbip_generator import infer_project
from pbip_generator.dictionary import render_diagram, render_dictionary
from pbip_generator.inference import is_rate_like

ROOT = Path(__file__).resolve().parents[1]
FUEL = ROOT / "examples" / "carburants"


def _folder(tmp_path: Path, files: dict[str, str]) -> Path:
    folder = tmp_path / "data"
    folder.mkdir()
    for name, content in files.items():
        (folder / name).write_text(content, encoding="utf-8")
    return folder


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Prix au litre", True),
        ("Prix unitaire", True),
        ("Unit price", True),
        ("Price per kg", True),
        ("Taux de marge", True),
        ("Marge %", True),
        ("Montant", False),
        ("Prix", False),  # a price alone is usually the amount paid
        ("Quantité", False),
        ("Score final", False),
    ],
)
def test_rate_like_names(name, expected):
    assert is_rate_like(name) is expected


def test_unit_price_gets_an_average_not_a_sum(tmp_path):
    folder = _folder(
        tmp_path,
        {
            "stations.csv": "StationID,Ville\n1,Paris\n2,Meaux\n",
            "releves.csv": "Date,StationID,Prix au litre\n2023-01-01,1,1.90\n2023-01-01,2,1.80\n",
        },
    )
    fact = infer_project(folder, "T").table("Releves")
    main = fact.measures[0]
    assert main.name == "Moyenne Prix au litre"
    assert main.expression == "AVERAGE(Releves[Prix au litre])"
    assert main.format_string == "#,##0.00 €"  # cents shown: an average price is not a round amount
    assert fact.column("Prix au litre").summarize_by == "average"
    assert not any(m.expression.startswith("SUM(") for m in fact.measures)


def test_english_average_name(tmp_path):
    from pbip_generator import ProjectConfig

    folder = _folder(tmp_path, {"sales.csv": "Date,Unit price,Amount\n2024-01-01,2.5,10\n"})
    names = {m.name for m in infer_project(folder, "T", config=ProjectConfig(language="en")).table("Sales").measures}
    assert {"Average Unit price", "Total Amount"} <= names


def test_grain_is_the_row_id_when_there_is_one():
    ventes = infer_project(ROOT / "examples" / "ventes" / "data", "Ventes").table("Ventes")
    assert ventes.grain == ["VenteID"]


def test_grain_is_the_smallest_unique_set_of_keys_and_dates():
    releves = infer_project(FUEL / "data", "Carburants").table("Releves")
    assert sorted(releves.grain) == ["Carburant", "Date relevé", "StationID"]


def test_grain_drops_columns_it_does_not_need(tmp_path):
    folder = _folder(
        tmp_path,
        {
            "clients.csv": "ClientID,Nom\n1,A\n2,B\n",
            "produits.csv": "ProduitID,Nom\n1,X\n2,Y\n",
            # one row per (date, client); the product is a property of the row, not part of its grain
            "ventes.csv": "Date,ClientID,ProduitID,Montant\n2024-01-01,1,1,5\n2024-01-01,2,1,7\n2024-01-02,1,2,3\n",
        },
    )
    assert infer_project(folder, "T").table("Ventes").grain == ["Date", "ClientID"]


def test_no_grain_when_rows_repeat(tmp_path):
    folder = _folder(
        tmp_path,
        {
            "clients.csv": "ClientID,Nom\n1,A\n2,B\n",
            "ventes.csv": "Date,ClientID,Montant\n2024-01-01,1,5\n2024-01-01,1,5\n2024-01-02,2,3\n",
        },
    )
    project = infer_project(folder, "T")
    assert project.table("Ventes").grain == []
    assert "aucune combinaison de ses clés et de ses dates n'est unique" in render_dictionary(project)


def test_diagram_lists_keys_and_relationships():
    project = infer_project(ROOT / "examples" / "ventes" / "data", "Ventes")
    diagram = render_diagram(project)
    assert diagram.startswith("```mermaid\nerDiagram\n") and diagram.endswith("```")
    assert 'T0["Ventes (faits)"] {' in diagram
    assert "int64 VenteID PK" in diagram  # the row ID of the fact table
    assert 'dateTime Date_commande FK "Date commande"' in diagram  # ASCII name, original kept as comment
    assert 'T0 }o..|| T3 : "Date livraison"' in diagram  # inactive relationship is dotted
    dictionary = render_dictionary(project)
    assert "## Schéma du modèle" in dictionary and "- **Ventes** : une ligne par `VenteID`" in dictionary


def test_readme_diagram_matches_the_generated_one():
    """The model diagram in the README is the one the tool generates for the public data example."""
    from pbip_generator import build_project_from_spec, load_spec

    project = build_project_from_spec(FUEL / "data", load_spec(FUEL / "report.yaml"), "Carburants")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert render_diagram(project) in readme, "README diagram is out of date: copy it from DATA_DICTIONARY.md"


def test_columns_created_inside_a_dax_expression_are_known(tmp_path):
    from pbip_generator import build_project_from_spec, parse_spec

    spec = parse_spec(
        {
            "name": "T",
            "business_question": "q",
            "audience": "direction",
            "measures": [
                {
                    "table": "Releves",
                    "name": "Écart",
                    "description": "d",
                    "expression": 'VAR t = ADDCOLUMNS(VALUES(Releves[StationID]), "@p", [Prix moyen])\n'
                    "RETURN MAXX(t, [@p]) - MINX(t, [@p])",
                },
                {
                    "table": "Releves",
                    "name": "Prix moyen",
                    "description": "d",
                    "expression": "AVERAGE(Releves[Prix au litre])",
                },
            ],
            "pages": [
                {
                    "name": "P",
                    "purpose": "p",
                    "template": "kpis_2",
                    "kpis": ["[Écart]"],
                    "visuals": [
                        {"type": "card", "title": "a", "values": ["[Prix moyen]"]},
                        {"type": "card", "title": "b", "values": ["[Écart]"]},
                    ],
                }
            ],
        }
    )
    folder = _folder(
        tmp_path,
        {
            "stations.csv": "StationID,Ville\n1,Paris\n2,Meaux\n",
            "releves.csv": "Date,StationID,Prix au litre\n2023-01-01,1,1.90\n2023-01-01,2,1.80\n",
        },
    )
    build_project_from_spec(folder, spec, "T")  # raises SpecError if [@p] is reported as unknown
