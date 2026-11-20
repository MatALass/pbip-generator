"""Built-in themes, color measures for highlights, slicer selection and table totals."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from pbip_generator import SpecError, build_project_from_spec, parse_spec, render_project
from pbip_generator.themes import PRESETS, build_theme, palette_for

ROOT = Path(__file__).resolve().parents[1]
SPEC = yaml.safe_load((ROOT / "examples" / "ventes" / "report.yaml").read_text(encoding="utf-8"))


def _with(**changes) -> dict:
    spec = json.loads(json.dumps(SPEC))
    for path, value in changes.items():
        *keys, last = path.split(".")
        node = spec
        for k in keys:
            node = node[int(k)] if k.isdigit() else node[k]
        node[last] = value
    return spec


def _visual_files(files: dict[str, str], visual_type: str) -> list[dict]:
    out = []
    for path, text in files.items():
        if path.endswith("visual.json") and json.loads(text)["visual"]["visualType"] == visual_type:
            out.append(json.loads(text)["visual"])
    return out


HIGHLIGHT = {
    "field": "[Total Montant]",
    "rules": [{"below": 20000, "color": "bad"}, {"below": 40000, "color": "neutral"}],
    "otherwise": "good",
}


def test_dark_theme_styles_pages_cards_and_tables():
    p = PRESETS["dark"]
    theme = build_theme("T", p)
    assert theme["visualStyles"]["page"]["*"]["background"][0]["color"]["solid"]["color"] == p.page
    card = theme["visualStyles"]["*"]["*"]
    assert card["border"][0]["radius"] == 10 and card["dropShadow"][0]["show"] is True
    assert theme["visualStyles"]["card"]["*"]["labels"][0]["color"]["solid"]["color"] == p.accent
    assert theme["dataColors"][:2] == [p.accent, p.secondary]
    assert palette_for("dark", accent="#123abc").accent == "#123ABC"


def test_spec_report_gets_its_theme_and_dark_titles(example_data):
    project = build_project_from_spec(example_data, parse_spec(_with(theme={"preset": "dark"})))
    files = render_project(project)
    themes = [k for k in files if k.endswith(".json") and "RegisteredResources" in k]
    assert len(themes) == 1 and json.loads(files[themes[0]])["name"] == "Ventes dark"
    (title, *_) = _visual_files(files, "textbox")
    run = title["objects"]["general"][0]["properties"]["paragraphs"][0]["textRuns"][0]
    assert run["textStyle"]["color"] == PRESETS["dark"].text
    report = json.loads(next(v for k, v in files.items() if k.endswith("definition/report.json")))
    assert report["settings"]["defaultFilterActionIsDataFilter"] is True


def test_highlight_becomes_a_hidden_color_measure(example_data):
    spec = _with(**{"pages.2.visuals.0.highlights": [HIGHLIGHT], "pages.2.visuals.0.totals": False})
    project = build_project_from_spec(example_data, parse_spec(spec))
    measure = next(m for m in project.table("Ventes").measures if m.name == "Couleur Total Montant")
    assert measure.is_hidden and measure.display_folder == "Couleurs"
    light = PRESETS["light"]
    assert f'_v < 20000, "{light.bad}"' in measure.expression and f'"{light.good}"' in measure.expression
    (table,) = [v for v in _visual_files(render_project(project), "tableEx") if "values" in v.get("objects", {})]
    rule = table["objects"]["values"][0]
    assert rule["selector"]["metadata"] == "Ventes.Total Montant"
    color = rule["properties"]["backColor"]["solid"]["color"]["expr"]["Measure"]
    assert color["Property"] == "Couleur Total Montant"
    assert table["objects"]["total"][0]["properties"]["totals"]["expr"]["Literal"]["Value"] == "false"


def test_card_highlight_colors_the_value(example_data):
    spec = _with(**{"pages.0.template": "kpis_2x2"})
    spec["pages"][0]["visuals"].append(
        {"type": "card", "title": "CA", "values": ["[Total Montant]"], "highlights": [HIGHLIGHT]}
    )
    files = render_project(build_project_from_spec(example_data, parse_spec(spec)))
    colored = [c for c in _visual_files(files, "card") if "labels" in c.get("objects", {})]
    assert len(colored) == 1


@pytest.mark.parametrize(
    ("highlight", "message"),
    [
        ({**HIGHLIGHT, "field": "[Clients actifs]"}, "must be one of the visual's values"),
        ({**HIGHLIGHT, "otherwise": "pink"}, "Unknown color 'pink'"),
        ({**HIGHLIGHT, "rules": [{"below": 5, "color": "bad"}, {"below": 1, "color": "good"}]}, "increasing"),
    ],
)
def test_bad_highlights_are_reported(example_data, highlight, message):
    spec = _with(**{"pages.2.visuals.0.highlights": [highlight]})
    with pytest.raises(SpecError) as exc:
        build_project_from_spec(example_data, parse_spec(spec))
    assert any(message in i for i in exc.value.issues)


def test_single_select_slicer(example_data):
    spec = _with(**{"pages.2.single_select": ["Clients[Région]"]})
    files = render_project(build_project_from_spec(example_data, parse_spec(spec)))
    selected = [s for s in _visual_files(files, "slicer") if "selection" in s["objects"]]
    assert len(selected) == 1
    props = selected[0]["objects"]["selection"][0]["properties"]
    assert props["strictSingleSelect"]["expr"]["Literal"]["Value"] == "true"
    bad = _with(**{"pages.2.single_select": ["Clients[Segment ]"]})
    with pytest.raises(SpecError, match="must be one of the page's slicers"):
        build_project_from_spec(example_data, parse_spec(bad))
