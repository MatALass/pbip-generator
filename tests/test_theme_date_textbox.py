"""Custom theme, CSV date table and textbox visuals."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pbip_generator import infer_project, render_project
from pbip_generator.config import ConfigError, ProjectConfig
from pbip_generator.model import Page, Visual

THEME = {"name": "Sable", "dataColors": ["#17A99B", "#E8662A"], "background": "#F1EADF"}


def _with_theme(example_data: Path, tmp_path: Path) -> dict[str, str]:
    (tmp_path / "sable.json").write_text(json.dumps(THEME), encoding="utf-8")
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("theme: sable.json\n", encoding="utf-8")
    return render_project(infer_project(example_data, "Ventes", config=ProjectConfig.load(cfg)))


def test_theme_is_registered_and_written(example_data, tmp_path):
    files = _with_theme(example_data, tmp_path)
    assert json.loads(files["Ventes.Report/StaticResources/RegisteredResources/Sable.json"]) == THEME
    report = json.loads(files["Ventes.Report/definition/report.json"])
    assert report["themeCollection"]["customTheme"]["name"] == "Sable.json"
    item = report["resourcePackages"][0]["items"][0]
    assert item == {"name": "Sable.json", "path": "Sable.json", "type": "CustomTheme"}


def test_theme_report_matches_schema(example_data, tmp_path, schema_validator):
    files = _with_theme(example_data, tmp_path)
    schema_validator(json.loads(files["Ventes.Report/definition/report.json"]))


def test_no_theme_keeps_empty_collection(example_data):
    files = render_project(infer_project(example_data, "Ventes"))
    report = json.loads(files["Ventes.Report/definition/report.json"])
    assert report["themeCollection"] == {} and "resourcePackages" not in report
    assert not any("StaticResources" in k for k in files)


def test_missing_theme_file_is_a_clear_error(example_data, tmp_path):
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("theme: nope.json\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Cannot read theme"):
        infer_project(example_data, "Ventes", config=ProjectConfig.load(cfg))


def _calendar_data(tmp_path: Path) -> Path:
    data = tmp_path / "cal"
    data.mkdir()
    (data / "calendrier.csv").write_text(
        "date_id,full_date,month_name\n20240101,2024-01-01,January\n20240102,2024-01-02,January\n", encoding="utf-8"
    )
    (data / "ventes.csv").write_text("id,date_id,montant\n1,20240101,10.5\n2,20240102,3.0\n", encoding="utf-8")
    return data


def test_csv_table_can_be_the_date_table(tmp_path):
    data = _calendar_data(tmp_path)
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("tables:\n  Calendrier:\n    role: date\n    key: full_date\n", encoding="utf-8")
    project = infer_project(data, "Ventes", config=ProjectConfig.load(cfg))
    files = render_project(project)
    cal = files["Ventes.SemanticModel/definition/tables/Calendrier.tmdl"]
    assert "\tdataCategory: Time" in cal
    assert 'File.Contents(DataFolder & "calendrier.csv")' in cal  # its own CSV, not a generated calendar
    assert "isKey" in cal.split("column full_date")[1].split("column ")[0]
    assert [t.name for t in project.tables].count("Calendrier") == 1


def test_date_table_without_key_is_rejected(tmp_path):
    data = _calendar_data(tmp_path)
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("tables:\n  Calendrier:\n    role: date\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="needs a 'key'"):
        infer_project(data, "Ventes", config=ProjectConfig.load(cfg))


def test_textbox_visual(example_data, schema_validator):
    project = infer_project(example_data, "Ventes")
    project.pages = [Page("Accueil", [Visual("textbox", {}, 16, 16, 600, 56, text="Ventes 2024", text_size=24)])]
    files = render_project(project)
    visual = next(json.loads(v) for k, v in files.items() if k.endswith("visual.json"))
    schema_validator(visual)
    run = visual["visual"]["objects"]["general"][0]["properties"]["paragraphs"][0]["textRuns"][0]
    assert run["value"] == "Ventes 2024" and run["textStyle"]["fontSize"] == "24pt"
    assert "query" not in visual["visual"]
