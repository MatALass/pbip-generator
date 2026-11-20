"""Every error path of the YAML config and of the spec validation, with the message it gives."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from pbip_generator import ConfigError, ProjectConfig, SpecError, build_project_from_spec, infer_project, parse_spec
from pbip_generator.model import DataType, TableRole

ROOT = Path(__file__).resolve().parents[1]
SPEC = yaml.safe_load((ROOT / "examples" / "ventes" / "report.yaml").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# config.py
# --------------------------------------------------------------------------- #
def _config(tmp_path: Path, text: str) -> ProjectConfig:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return ProjectConfig.load(path)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("- a\n- b\n", "root must be a mapping"),
        ("colour: red\n", "Unknown config keys: ['colour']"),
    ],
)
def test_config_file_errors(tmp_path, text, message):
    with pytest.raises(ConfigError, match=message.replace("[", r"\[").replace("]", r"\]")):
        _config(tmp_path, text)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("tables:\n  Ventes:\n    role: cube\n", "Invalid role for 'Ventes': cube"),
        ("tables:\n  Ventes:\n    types: {Montant: money}\n", "Invalid type 'money' for Ventes[Montant]"),
        ("tables:\n  Factures:\n    role: fact\n", "unknown table 'Factures'"),
        ("tables:\n  Clients:\n    role: date\n", "needs a 'key' column"),
        (
            "relationships:\n  add:\n    - {from: Ventes.ClientID, to: 'Clients[ClientID]'}\n",
            "Invalid column reference",
        ),
        (
            "relationships:\n  add:\n    - {from: 'Ventes[Client]', to: 'Clients[ClientID]'}\n",
            "Column 'Client' not found",
        ),
        ("tables:\n  Ventes:\n    measures:\n      - {name: CA}\n", "needs 'name' and 'expression'"),
    ],
)
def test_config_structure_errors(example_data, tmp_path, text, message):
    with pytest.raises(ConfigError, match=message.replace("[", r"\[").replace("]", r"\]")):
        infer_project(example_data, "Ventes", config=_config(tmp_path, text))


def test_config_type_changes(example_data, tmp_path):
    config = _config(tmp_path, "tables:\n  Ventes:\n    types: {Quantité: string, VenteID: dateTime}\n")
    ventes = infer_project(example_data, "Ventes", config=config).table("Ventes")
    quantity, sale_id = ventes.column("Quantité"), ventes.column("VenteID")
    assert quantity.data_type == DataType.STRING and quantity.summarize_by == "none" and quantity.format_string is None
    assert sale_id.data_type == DataType.DATETIME and sale_id.is_date_only and sale_id.format_string == "dd/mm/yyyy"
    assert "Total Quantité" not in {m.name for m in ventes.measures}


def test_config_relationships_add_remove_and_role(example_data, tmp_path):
    config = _config(
        tmp_path,
        "relationships:\n"
        "  remove:\n    - {from: 'Ventes[ProduitID]', to: 'Produits[ProduitID]'}\n"
        "  add:\n    - {from: 'Produits[ProduitID]', to: 'Ventes[VenteID]', active: false}\n",
    )
    project = infer_project(example_data, "Ventes", config=config)
    rels = {(r.from_table, r.from_column, r.to_table, r.is_active) for r in project.relationships}
    assert ("Ventes", "ProduitID", "Produits", True) not in rels
    assert ("Produits", "ProduitID", "Ventes", False) in rels
    assert project.table("Produits").role == TableRole.FACT  # now only on the many side


def test_config_theme_errors(example_data, tmp_path):
    (tmp_path / "theme.json").write_text(json.dumps({"dataColors": []}), encoding="utf-8")
    with pytest.raises(ConfigError, match="must be a JSON object with a 'name'"):
        infer_project(example_data, "Ventes", config=_config(tmp_path, "theme: theme.json\n"))
    with pytest.raises(ConfigError, match="Cannot read theme"):
        infer_project(example_data, "Ventes", config=_config(tmp_path, "theme: missing.json\n"))


# --------------------------------------------------------------------------- #
# validate.py
# --------------------------------------------------------------------------- #
def _issues(example_data, change) -> list[str]:
    spec = copy.deepcopy(SPEC)
    change(spec)
    with pytest.raises(SpecError) as exc:
        build_project_from_spec(example_data, parse_spec(spec))
    return exc.value.issues


def _set(path: str, value):
    def change(spec):
        *keys, last = path.split(".")
        node = spec
        for k in keys:
            node = node[int(k)] if k.isdigit() else node[k]
        node[int(last) if last.isdigit() else last] = value

    return change


def _visual(page: int, visual: dict):
    def change(spec):
        spec["pages"][page]["visuals"][0] = visual

    return change


TITLE = {"title": "T"}
CA = "[Total Montant]"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (_set("pages.0.kpis.0", "Total Montant"), "is not a field reference"),
        (_set("pages.0.slicers.0", "Factures[Année]"), "unknown table 'Factures'"),
        (_set("pages.0.slicers.0", CA), "is a measure, a column is expected here"),
        (_set("measures.0.expression", "SUM('Factures'[Montant])"), "unknown table 'Factures'"),
        (_set("measures.1", {**SPEC["measures"][0], "table": "Clients"}), "'Panier moyen' is in both"),
        (_set("pages.1.name", "Synthèse"), "several pages are named 'Synthèse'"),
        (_set("pages.2.kpis", [CA]), "template 'table' has no KPI row"),
        (_visual(2, {"type": "textbox"}), "a textbox needs 'text'"),
        (_visual(2, {"type": "textbox", "text": "x", "values": [CA]}), "a textbox takes no field"),
        (_visual(2, {"type": "tableEx", "values": [CA]}), "a tableEx needs a 'title'"),
        (_visual(2, {"type": "tableEx", **TITLE}), "needs at least one entry in 'values'"),
        (_visual(2, {"type": "lineChart", "values": [CA], **TITLE}), "needs a 'category' column"),
        (
            _visual(2, {"type": "donutChart", "category": "Clients[Segment]", "values": [CA, "[Nb Ventes]"], **TITLE}),
            "a donutChart shows a single measure",
        ),
        (
            _visual(2, {"type": "tableEx", "category": "Clients[Segment]", "values": [CA], **TITLE}),
            "takes no 'category'",
        ),
        (_visual(2, {"type": "card", "values": [CA, "[Nb Ventes]"], **TITLE}), "a card shows a single measure"),
        (
            _visual(2, {"type": "tableEx", "values": [CA], "sort_by": "[Nb Ventes]", **TITLE}),
            "must be one of the visual",
        ),
        (_visual(2, {"type": "tableEx", "values": [CA], "totals": False, **TITLE}), None),
        (
            _visual(2, {"type": "card", "values": [CA], "totals": False, **TITLE}),
            "'totals' applies to a tableEx or a pivotTable only",
        ),
        (
            _visual(
                2,
                {
                    "type": "lineChart",
                    "category": "Calendrier[Année-Mois]",
                    "values": [CA],
                    "highlights": [{"field": CA, "rules": [{"below": 1, "color": "bad"}], "otherwise": "good"}],
                    **TITLE,
                },
            ),
            "highlights apply to a tableEx, a pivotTable or a card",
        ),
        (
            _visual(
                2,
                {
                    "type": "tableEx",
                    "values": ["Clients[Région]", CA],
                    "highlights": [
                        {"field": "Clients[Région]", "rules": [{"below": 1, "color": "bad"}], "otherwise": "good"}
                    ],
                    **TITLE,
                },
            ),
            "is a column, highlights color a measure",
        ),
    ],
)
def test_spec_validation_messages(example_data, change, message):
    if message is None:  # a valid variant, to make sure the rule above is not too broad
        spec = copy.deepcopy(SPEC)
        change(spec)
        build_project_from_spec(example_data, parse_spec(spec))
        return
    issues = _issues(example_data, change)
    assert any(message in i for i in issues), issues


def test_measure_on_unknown_table_is_reported_once(example_data):
    issues = _issues(example_data, _set("measures.0.table", "Factures"))
    assert len(issues) == 1 and "Factures" in issues[0]


def test_qualified_measure_reference_resolves(example_data):
    spec = copy.deepcopy(SPEC)
    spec["pages"][0]["kpis"][0] = "Ventes[Total Montant]"
    page = build_project_from_spec(example_data, parse_spec(spec)).pages[0]
    card = next(v for v in page.visuals if v.visual_type == "card")
    assert card.roles["Values"][0].is_measure


def test_unquoted_variable_before_brackets_is_not_a_table(example_data):
    spec = copy.deepcopy(SPEC)
    spec["measures"][0]["expression"] = "VAR t = Ventes RETURN DIVIDE([Total Montant], [Nb Ventes])"
    build_project_from_spec(example_data, parse_spec(spec))
