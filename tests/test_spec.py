"""Report spec: parsing, validation against the model, page templates and the CLI."""

from __future__ import annotations

import copy
import json
import warnings
from pathlib import Path

import pytest
import yaml

from pbip_generator import SpecError, build_project_from_spec, check_project, infer_project, parse_spec, render_project
from pbip_generator.cli import main
from pbip_generator.spec import TEMPLATE_SLOTS
from pbip_generator.templates import body_slots

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_SPEC = ROOT / "examples" / "ventes" / "report.yaml"


@pytest.fixture
def raw_spec() -> dict:
    return yaml.safe_load(EXAMPLE_SPEC.read_text(encoding="utf-8"))


def _issues(example_data, raw: dict) -> list[str]:
    with pytest.raises(SpecError) as exc:
        build_project_from_spec(example_data, parse_spec(raw))
    return exc.value.issues


def test_example_spec_builds_without_layout_issue(example_data, raw_spec):
    project = build_project_from_spec(example_data, parse_spec(raw_spec))
    assert [p.display_name for p in project.pages] == ["Synthèse", "Produits", "Clients"]
    assert check_project(project) == []
    assert project.table("Ventes").measures[-1].description == "Nombre de clients ayant acheté sur la période"
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        render_project(project, strict=True)


def test_spec_report_files_match_microsoft_schemas(example_data, raw_spec, schema_validator):
    files = render_project(build_project_from_spec(example_data, parse_spec(raw_spec)))
    checked = 0
    for path, text in files.items():
        if path.endswith(".json") or path.endswith(".pbir") or path.endswith(".pbip"):
            data = json.loads(text)
            if "$schema" in data:
                schema_validator(data)
                checked += 1
    assert checked > 20


def test_page_has_title_slicers_kpis_then_template_visuals(example_data, raw_spec):
    page = build_project_from_spec(example_data, parse_spec(raw_spec)).pages[0]
    types = [v.visual_type for v in page.visuals]
    assert types == ["textbox", "slicer", "slicer", "card", "card", "card", "card"] + [
        "lineChart",
        "clusteredBarChart",
        "donutChart",
    ]
    line = page.visuals[7]
    assert line.sort_by.name == "Année-Mois" and line.sort_descending is False


@pytest.mark.parametrize("template", sorted(TEMPLATE_SLOTS))
def test_templates_fill_the_body(template):
    slots = body_slots(template, 224)
    assert len(slots) == TEMPLATE_SLOTS[template]
    assert max(y + h for _, y, _, h in slots) == pytest.approx(704)


def test_unknown_key_is_rejected(raw_spec):
    raw_spec["pages"][0]["visuals"][0]["colour"] = "red"
    with pytest.raises(SpecError, match="colour"):
        parse_spec(raw_spec)


def test_missing_purpose_is_rejected(raw_spec):
    del raw_spec["pages"][0]["purpose"]
    with pytest.raises(SpecError, match="purpose"):
        parse_spec(raw_spec)


def test_unknown_measure_suggests_close_names(example_data, raw_spec):
    raw_spec["pages"][0]["kpis"][0] = "[Total Montan]"
    (issue,) = _issues(example_data, raw_spec)
    assert "kpis[0]" in issue and "did you mean Total Montant" in issue


def test_unknown_column_lists_the_table(example_data, raw_spec):
    raw_spec["pages"][0]["slicers"][1] = "Clients[Ville]"
    (issue,) = _issues(example_data, raw_spec)
    assert "'Clients' has no column or measure 'Ville'" in issue


def test_column_where_a_measure_is_expected(example_data, raw_spec):
    raw_spec["pages"][0]["visuals"][1]["values"] = ["Ventes[Montant]"]
    (issue,) = _issues(example_data, raw_spec)
    assert "a measure is expected" in issue


def test_hidden_key_column_is_refused(example_data, raw_spec):
    raw_spec["pages"][2]["visuals"][0]["values"][0] = "Ventes[ClientID]"
    assert any("hidden technical column" in i for i in _issues(example_data, raw_spec))


def test_wrong_visual_count_suggests_templates(example_data, raw_spec):
    raw_spec["pages"][0]["visuals"].pop()
    (issue,) = _issues(example_data, raw_spec)
    assert "holds 3 visual(s), got 2" in issue and "kpis_2" in issue


def test_kpi_template_needs_kpis(example_data, raw_spec):
    raw_spec["pages"][1]["kpis"] = []
    assert any("needs 1 to 4 'kpis'" in i for i in _issues(example_data, raw_spec))


def test_too_many_categories_for_a_donut(example_data, raw_spec):
    raw_spec["pages"][0]["visuals"][2]["category"] = "Produits[Produit]"
    assert any("stays readable up to 6" in i for i in _issues(example_data, raw_spec))


def test_dax_reference_to_unknown_measure(example_data, raw_spec):
    raw_spec["measures"][0]["expression"] = 'DIVIDE([Total Montant], [Nb Commandes]) // "[ignored]"'
    (issue,) = _issues(example_data, raw_spec)
    assert issue.startswith("measure 'Panier moyen': [Nb Commandes]")


def test_dax_reference_to_unknown_column(example_data, raw_spec):
    raw_spec["measures"][1]["expression"] = "DISTINCTCOUNT(Ventes[Client])"
    (issue,) = _issues(example_data, raw_spec)
    assert "Ventes[Client] does not exist" in issue


def test_measure_named_like_a_column(example_data, raw_spec):
    raw_spec["measures"][0]["name"] = "Montant"
    assert any("has the name of a column" in i for i in _issues(example_data, raw_spec))


def test_unknown_table_in_overrides_is_a_spec_error(example_data, raw_spec):
    raw_spec["tables"] = {"Factures": {"role": "fact"}}
    (issue,) = _issues(example_data, raw_spec)
    assert "Factures" in issue and "Ventes" in issue


def test_cli_build_with_spec(example_data, tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["build", str(example_data), "--spec", str(EXAMPLE_SPEC), "-o", str(out), "--strict"]) == 0
    pages = json.loads((out / "Ventes" / "Ventes.Report" / "definition" / "pages" / "pages.json").read_text("utf-8"))
    assert len(pages["pageOrder"]) == 3


def test_cli_reports_spec_issues(example_data, tmp_path, raw_spec, capsys):
    bad = copy.deepcopy(raw_spec)
    bad["pages"][0]["kpis"][0] = "[Nope]"
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
    assert main(["build", str(example_data), "--spec", str(path), "-o", str(tmp_path / "out")]) == 1
    assert "unknown measure [Nope]" in capsys.readouterr().err


def test_cli_spec_and_config_are_exclusive(example_data, tmp_path, capsys):
    config = ROOT / "examples" / "ventes" / "config.yaml"
    args = ["build", str(example_data), "--spec", str(EXAMPLE_SPEC), "-c", str(config), "-o", str(tmp_path)]
    assert main(args) == 1
    assert "cannot be used together" in capsys.readouterr().err


def test_cli_prints_schema(capsys):
    assert main(["spec-schema"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert "pages" in schema["required"] and "PageSpec" in schema["$defs"]


def test_crowded_chart_suggests_charts_that_fit(example_data, raw_spec):
    raw_spec["pages"][0]["visuals"][1]["category"] = "Produits[Produit]"  # 25 products in a bar chart
    (issue,) = _issues(example_data, raw_spec)
    assert issue.endswith("use a tableEx or a column with fewer values")
    raw_spec["pages"][0]["visuals"][1]["category"] = "Clients[Région]"
    raw_spec["pages"][0]["visuals"][2]["category"] = "Calendrier[Mois]"  # 12 months in a donut
    (issue,) = _issues(example_data, raw_spec)
    assert "use a clusteredColumnChart or a clusteredBarChart or a tableEx" in issue


def test_calendar_columns_count_their_values(example_data, raw_spec):
    project = build_project_from_spec(example_data, parse_spec(raw_spec))
    cal = project.table("Calendrier")
    assert cal.column("Année").distinct_count == 3  # orders in 2024-2025, a few deliveries in 2026
    assert cal.column("Année-Mois").distinct_count == 36
    raw_spec["pages"][0]["visuals"][2]["category"] = "Calendrier[Année-Mois]"
    assert any("has 36 values" in i for i in _issues(example_data, raw_spec))


def test_technical_keys_are_hidden(example_data):
    project = infer_project(example_data, "Ventes")
    assert project.table("Clients").column("ClientID").is_hidden
    assert project.table("Produits").column("ProduitID").is_hidden
    assert project.table("Ventes").column("VenteID").is_hidden
    assert not project.table("Calendrier").column("Date").is_hidden
    assert not project.table("Clients").column("Nom client").is_hidden
