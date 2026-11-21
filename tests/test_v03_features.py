"""Matrix visual, French/English generated names, data dictionary."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from pbip_generator import (
    ConfigError,
    ProjectConfig,
    SpecError,
    build_project_from_spec,
    infer_project,
    parse_spec,
    render_project,
)
from pbip_generator.cli import main
from pbip_generator.dictionary import render_dictionary
from pbip_generator.labels import LABELS

ROOT = Path(__file__).resolve().parents[1]
SPEC = yaml.safe_load((ROOT / "examples" / "ventes" / "report.yaml").read_text(encoding="utf-8"))

MATRIX = {
    "type": "pivotTable",
    "title": "CA par catégorie et par année",
    "rows": ["Produits[Catégorie]", "Produits[Produit]"],
    "columns": ["Calendrier[Année]"],
    "values": ["[Total Montant]"],
}


def _with_matrix(**changes) -> dict:
    spec = copy.deepcopy(SPEC)
    spec["pages"][2]["visuals"][0] = {**MATRIX, **changes}
    return spec


def _visuals(files: dict[str, str], visual_type: str) -> list[dict]:
    return [
        json.loads(text)["visual"]
        for path, text in files.items()
        if path.endswith("visual.json") and json.loads(text)["visual"]["visualType"] == visual_type
    ]


# --------------------------------------------------------------------------- #
# Matrix
# --------------------------------------------------------------------------- #
def test_matrix_has_rows_columns_and_values(example_data):
    highlight = {"field": "[Total Montant]", "rules": [{"below": 10000, "color": "bad"}], "otherwise": "good"}
    spec = _with_matrix(totals=False, highlights=[highlight])
    files = render_project(build_project_from_spec(example_data, parse_spec(spec)))
    (matrix,) = [v for v in _visuals(files, "pivotTable") if "values" in v.get("objects", {})]
    state = matrix["query"]["queryState"]
    assert [p["queryRef"] for p in state["Rows"]["projections"]] == ["Produits.Catégorie", "Produits.Produit"]
    assert [p["queryRef"] for p in state["Columns"]["projections"]] == ["Calendrier.Année"]
    assert [p["queryRef"] for p in state["Values"]["projections"]] == ["Ventes.Total Montant"]
    assert matrix["query"]["sortDefinition"]["sort"][0]["field"]["Measure"]["Property"] == "Total Montant"
    subtotals = matrix["objects"]["subTotals"][0]["properties"]
    assert subtotals["rowSubtotals"]["expr"]["Literal"]["Value"] == "false"
    assert matrix["objects"]["values"][0]["selector"]["metadata"] == "Ventes.Total Montant"


def test_matrix_without_columns_and_with_time_rows(example_data):
    spec = _with_matrix(rows=["Calendrier[Année-Mois]"], columns=[])
    page = build_project_from_spec(example_data, parse_spec(spec)).pages[2]
    matrix = next(v for v in page.visuals if v.visual_type == "pivotTable")
    assert "Columns" not in matrix.roles
    assert matrix.sort_by.name == "Année-Mois" and matrix.sort_descending is False


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"rows": []}, "needs at least one column in 'rows'"),
        ({"rows": ["[Total Montant]"]}, "is a measure, a column is expected"),
        ({"columns": ["Clients[Région]", "Clients[Segment]"]}, "takes one column in 'columns'"),
        ({"columns": ["Produits[Produit]"]}, "25 values, too many column headers"),
        ({"category": "Clients[Région]"}, "takes 'rows' and 'columns', not 'category'"),
        ({"rows": ["Clients[Région]", "Clients[Segment]", "Produits[Catégorie]", "Produits[Produit]"]}, "3 row levels"),
        ({"values": ["Ventes[Montant]"]}, "a measure is expected"),
    ],
)
def test_matrix_validation(example_data, changes, message):
    with pytest.raises(SpecError) as exc:
        build_project_from_spec(example_data, parse_spec(_with_matrix(**changes)))
    assert any(message in i for i in exc.value.issues), exc.value.issues


# --------------------------------------------------------------------------- #
# Language
# --------------------------------------------------------------------------- #
def test_english_names(example_data):
    project = infer_project(example_data, "Sales", config=ProjectConfig(language="en"))
    assert project.culture == "en-US" and project.date_table.name == "Calendar"
    assert [c.name for c in project.date_table.columns][1:4] == ["Year", "Quarter", "Month Number"]
    measures = {m.name: m for m in project.table("Ventes").measures}
    assert {"Total Montant", "Ventes Count", "Total Montant PY", "Total Montant YoY %", "Total Montant YTD"} <= set(
        measures
    )
    assert "[Total Montant PY]" in measures["Total Montant YoY %"].expression
    assert measures["Total Montant"].format_string == "$#,##0"
    files = render_project(project)
    pages = [json.loads(v)["displayName"] for k, v in files.items() if k.endswith("page.json")]
    assert pages == ["Overview", "Detail"]
    calendar = files["Sales.SemanticModel/definition/tables/Calendar.tmdl"]
    assert '"Quarter", each "Q" & ' in calendar and '"en-US"' in calendar
    titles = [v["visualContainerObjects"]["title"][0]["properties"]["text"] for v in _visuals(files, "lineChart")]
    assert titles[0]["expr"]["Literal"]["Value"] == "'Total Montant by Month'"


def test_english_keeps_an_explicit_culture(example_data):
    project = infer_project(example_data, "Sales", config=ProjectConfig(language="en", culture="fr-FR"))
    assert project.culture == "fr-FR" and project.table("Ventes").measures[0].format_string == "#,##0 €"


def test_french_stays_the_default(example_data):
    project = infer_project(example_data, "Ventes")
    assert project.language == "fr" and project.date_table.name == "Calendrier"


def test_every_language_has_every_label():
    assert set(LABELS["fr"]) == set(LABELS["en"])


def test_unknown_language_is_a_config_error(tmp_path):
    (tmp_path / "c.yaml").write_text("language: de\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Invalid language 'de'"):
        ProjectConfig.load(tmp_path / "c.yaml")


def test_spec_in_english(example_data):
    text = json.dumps(SPEC, ensure_ascii=False)
    for french, english in [
        ("[Nb Ventes]", "[Ventes Count]"),
        ("Var % N-1]", "YoY %]"),
        ("Calendrier[Année-Mois]", "Calendar[Year-Month]"),
        ("Calendrier[Année]", "Calendar[Year]"),
    ]:
        text = text.replace(french, english)
    spec = json.loads(text)
    spec["language"] = "en"
    spec["pages"][2]["visuals"][0]["highlights"] = [
        {"field": "[Total Montant]", "rules": [{"below": 1, "color": "bad"}], "otherwise": "good"}
    ]
    project = build_project_from_spec(example_data, parse_spec(spec))
    assert "Total Montant Color" in {m.name for m in project.table("Ventes").measures}


def test_cli_language_flag(example_data, tmp_path):
    assert main(["build", str(example_data), "-o", str(tmp_path), "-n", "Sales", "-l", "en"]) == 0
    assert (tmp_path / "Sales" / "Sales.SemanticModel" / "definition" / "tables" / "Calendar.tmdl").is_file()
    config = tmp_path / "c.yaml"
    assert main(["init-config", str(example_data), "-o", str(config), "-l", "en"]) == 0
    text = config.read_text(encoding="utf-8")
    assert "language: en" in text and "Ventes Count" in text


# --------------------------------------------------------------------------- #
# Data dictionary
# --------------------------------------------------------------------------- #
def test_dictionary_lists_tables_columns_relationships_and_measures(example_data):
    project = build_project_from_spec(example_data, parse_spec(SPEC))
    text = render_dictionary(project)
    assert text.startswith("# Dictionnaire de données : Ventes\n")
    assert "| Ventes | faits | `ventes.csv` | 2 000 | 7 | 8 |" in text
    assert "| Calendrier | dates | table générée (Power Query) |  | 8 | 0 |" in text
    assert "| ClientID | int64 |  | oui |" in text
    assert "| Ventes[Date livraison] | Calendrier[Date] | non |" in text
    assert "| Panier moyen | Ventes | KPI | `#,##0.00 €` | Montant moyen d'une vente |" in text
    assert "```dax\nDIVIDE([Total Montant], [Nb Ventes])\n```" in text
    # Facts come before dimensions, the calendar last.
    assert text.index("### Ventes") < text.index("### Clients") < text.index("### Calendrier")


def test_dictionary_in_english_marks_hidden_measures(example_data):
    spec = copy.deepcopy(SPEC)
    spec["pages"][2]["visuals"][0]["highlights"] = [
        {"field": "[Total Montant]", "rules": [{"below": 1, "color": "bad"}], "otherwise": "good"}
    ]
    project = build_project_from_spec(example_data, parse_spec(spec))
    project.language = "en"
    text = render_dictionary(project)
    assert text.startswith("# Data dictionary: Ventes\n") and "| Couleur Total Montant (hidden) |" in text


def test_dictionary_escapes_pipes():
    from pbip_generator.dictionary import _cell

    assert _cell("a|b") == "a\\|b" and _cell(None) == "" and _cell("x\ny") == "x y"


def test_dictionary_is_written_with_the_project_and_by_the_cli(example_data, tmp_path, capsys):
    assert main(["build", str(example_data), "-o", str(tmp_path), "-n", "Ventes"]) == 0
    assert (tmp_path / "Ventes" / "DATA_DICTIONARY.md").read_text(encoding="utf-8").startswith("# Dictionnaire")
    capsys.readouterr()
    assert main(["dictionary", str(example_data), "--spec", str(ROOT / "examples/ventes/report.yaml")]) == 0
    assert "Panier moyen" in capsys.readouterr().out
    out = tmp_path / "dico.md"
    assert main(["dictionary", str(example_data), "-l", "en", "-o", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Data dictionary: ")


# --------------------------------------------------------------------------- #
# Scatter chart
# --------------------------------------------------------------------------- #
SCATTER = {
    "type": "scatterChart",
    "title": "Panier moyen et nombre de ventes par client",
    "category": "Clients[Nom client]",
    "values": ["[Nb Ventes]", "[Panier moyen]", "[Total Montant]"],
}


def test_scatter_has_one_point_per_category_and_x_y_size(example_data):
    spec = _with_matrix()
    spec["pages"][2]["visuals"][0] = {**SCATTER, "filters": [{"field": "[Nb Ventes]", "operator": ">=", "value": 2}]}
    files = render_project(build_project_from_spec(example_data, parse_spec(spec)))
    (scatter,) = _visuals(files, "scatterChart")
    state = scatter["query"]["queryState"]
    assert [p["queryRef"] for p in state["Category"]["projections"]] == ["Clients.Nom client"]
    assert [p["queryRef"] for p in state["X"]["projections"]] == ["Ventes.Nb Ventes"]
    assert [p["queryRef"] for p in state["Y"]["projections"]] == ["Ventes.Panier moyen"]
    assert [p["queryRef"] for p in state["Size"]["projections"]] == ["Ventes.Total Montant"]
    assert "sortDefinition" not in scatter["query"]


def test_scatter_without_size(example_data):
    spec = _with_matrix()
    spec["pages"][2]["visuals"][0] = {**SCATTER, "values": SCATTER["values"][:2]}
    files = render_project(build_project_from_spec(example_data, parse_spec(spec)))
    (scatter,) = _visuals(files, "scatterChart")
    assert set(scatter["query"]["queryState"]) == {"Category", "X", "Y"}


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"category": None}, "needs a 'category' column"),
        ({"values": ["[Nb Ventes]"]}, "takes 2 or 3 measures"),
        ({"values": ["[Nb Ventes]", "Clients[Région]"]}, "a measure is expected"),
        ({"category": "[Nb Ventes]"}, "a column is expected"),
    ],
)
def test_scatter_spec_errors(example_data, changes, message):
    spec = _with_matrix()
    spec["pages"][2]["visuals"][0] = {**SCATTER, **changes}
    with pytest.raises(SpecError, match=message):
        build_project_from_spec(example_data, parse_spec(spec))
