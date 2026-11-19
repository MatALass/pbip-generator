from __future__ import annotations

import json
import re
from pathlib import Path

from pbip_generator import infer_project, render_project, write_project
from pbip_generator.config import ProjectConfig


def _files(example_data: Path, **kw) -> dict[str, str]:
    return render_project(infer_project(example_data, "Ventes", "C:\\Data\\", **kw))


def test_all_json_files_match_microsoft_schemas(example_data, schema_validator):
    files = _files(example_data)
    json_files = [k for k in files if k.endswith((".json", ".pbir", ".pbism", ".pbip", ".platform"))]
    assert len(json_files) > 10
    for name in json_files:
        try:
            schema_validator(json.loads(files[name]))
        except AssertionError as exc:  # pragma: no cover - diagnostic message
            raise AssertionError(f"{name}:\n{exc}") from None


def test_project_layout(example_data):
    files = _files(example_data)
    assert "Ventes.pbip" in files
    assert "Ventes.Report/definition.pbir" in files
    assert "Ventes.SemanticModel/definition/model.tmdl" in files
    assert "Ventes.SemanticModel/definition/tables/Ventes.tmdl" in files
    pbir = json.loads(files["Ventes.Report/definition.pbir"])
    assert pbir["datasetReference"]["byPath"]["path"] == "../Ventes.SemanticModel"
    pages = json.loads(files["Ventes.Report/definition/pages/pages.json"])
    assert len(pages["pageOrder"]) == 2


def test_tmdl_structure(example_data):
    files = _files(example_data)
    tables = {k: v for k, v in files.items() if "/definition/tables/" in k}
    for name, text in tables.items():
        assert text.startswith("table "), name
        assert "\tpartition " in text and "\t\tmode: import" in text, name
        for line in text.splitlines():
            assert not line.startswith(" "), f"{name}: space indentation: {line!r}"
    ventes = files["Ventes.SemanticModel/definition/tables/Ventes.tmdl"]
    assert "measure 'Total Montant' = SUM(Ventes[Montant])" in ventes
    assert 'File.Contents(DataFolder & "ventes.csv")' in ventes
    expr = files["Ventes.SemanticModel/definition/expressions.tmdl"]
    assert expr.startswith('expression DataFolder = "C:\\Data\\" meta')


def test_relationships_reference_existing_columns(example_data):
    project = infer_project(example_data, "Ventes")
    rels = render_project(project)["Ventes.SemanticModel/definition/relationships.tmdl"]
    for t, c in re.findall(r"Column: ('?[^.]+'?)\.('?.+'?)$", rels, flags=re.M):
        table = project.table(t.strip("'"))
        assert table.has_column(c.strip("'"))


def test_visuals_reference_existing_fields(example_data):
    project = infer_project(example_data, "Ventes")
    files = render_project(project)
    names = {(t.name, c.name) for t in project.tables for c in t.columns}
    names |= {(t.name, m.name) for t, m in project.all_measures()}
    for path, text in files.items():
        if path.endswith("visual.json"):
            for ent, prop in re.findall(r'"Entity": "(.+?)"\s*}\s*},\s*"Property": "(.+?)"', text):
                assert (ent, prop) in names, (path, ent, prop)


def test_generation_is_deterministic(example_data):
    assert _files(example_data) == _files(example_data)


def test_config_overrides(example_data, tmp_path):
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        """
date_table: false
tables:
  Ventes:
    hide: [Quantité]
    measures:
      - name: Panier moyen
        expression: DIVIDE([Total Montant], [Nb Ventes])
        format: '#,##0.00 €'
relationships:
  remove:
    - from: Ventes[ProduitID]
      to: Produits[ProduitID]
""",
        encoding="utf-8",
    )
    project = infer_project(example_data, "Ventes", config=ProjectConfig.load(cfg))
    assert project.date_table is None
    assert not any(r.to_table == "Produits" for r in project.relationships)
    assert project.table("Ventes").column("Quantité").is_hidden
    panier = next(m for m in project.table("Ventes").measures if m.name == "Panier moyen")
    assert panier.format_string == "#,##0.00 €"


def test_write_project(example_data, tmp_path):
    root = write_project(infer_project(example_data, "Ventes"), tmp_path / "out", copy_data=True)
    assert (root / "Ventes.pbip").is_file()
    assert (root / "data" / "ventes.csv").is_file()
    raw = (root / "Ventes.SemanticModel/definition/model.tmdl").read_bytes()
    assert b"\r\n" not in raw


def test_custom_measures_only_still_build_report_pages(example_data, tmp_path):
    """auto_measures: false with measures in custom folders must not give an empty report."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """auto_measures: false
tables:
  Ventes:
    measures:
      - name: Chiffre d'affaires
        expression: SUM(Ventes[Montant])
        format: '#,##0 €'
        folder: KPI
      - name: Nombre de ventes
        expression: COUNTROWS(Ventes)
        folder: KPI
""",
        encoding="utf-8",
    )
    project = infer_project(example_data, "Ventes", config=ProjectConfig.load(cfg))
    files = render_project(project)
    pages = json.loads(files["Ventes.Report/definition/pages/pages.json"])
    assert len(pages["pageOrder"]) == 2
    visuals = "\n".join(v for k, v in files.items() if k.endswith("visual.json"))
    assert "Chiffre d'affaires" in visuals
