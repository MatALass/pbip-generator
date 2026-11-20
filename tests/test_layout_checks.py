"""Layout checks and the slicer/card rendering that keeps their data visible."""

from __future__ import annotations

import json
import warnings

import pytest

from pbip_generator import LayoutError, check_project, infer_project, render_project
from pbip_generator.checks import check_page, check_pages
from pbip_generator.cli import main
from pbip_generator.layout import CHART_MAX_CATEGORIES, build_pages
from pbip_generator.model import FieldRef, Page, Visual

MEASURE = FieldRef("Ventes", "Total Montant", is_measure=True)
CATEGORY = FieldRef("Clients", "Segment")


def _card(x, y, w=200, h=100):
    return Visual("card", {"Values": [MEASURE]}, x, y, w, h, title="Total Montant")


def _visuals(files: dict[str, str], visual_type: str) -> list[dict]:
    out = []
    for path, text in files.items():
        if path.endswith("visual.json"):
            data = json.loads(text)
            if data["visual"]["visualType"] == visual_type:
                out.append(data)
    return out


def test_automatic_layout_has_no_issue(example_data):
    assert check_project(infer_project(example_data, "Ventes")) == []


def test_overlap_is_reported():
    issues = check_page(Page("P", [_card(0, 0), _card(150, 50)]))
    assert len(issues) == 1 and "overlaps" in issues[0].message


def test_touching_visuals_do_not_overlap():
    assert check_page(Page("P", [_card(0, 0), _card(200, 0), _card(0, 100)])) == []


def test_visual_outside_page_is_reported():
    issues = check_page(Page("P", [_card(1200, 0)]))
    assert any("outside" in i.message for i in issues)


def test_too_small_slicer_is_reported():
    slicer = Visual("slicer", {"Values": [CATEGORY]}, 0, 0, 200, 40, title="Segment")
    issues = check_page(Page("P", [slicer]))
    assert len(issues) == 1 and "too small" in issues[0].message


def test_visual_without_field_is_reported():
    issues = check_page(Page("P", [Visual("card", {"Values": []}, 0, 0, 200, 100)]))
    assert any("no field" in i.message for i in issues)


def test_duplicate_page_names_are_reported():
    issues = check_pages([Page("Vue"), Page("Vue")])
    assert issues and issues[0].message == "several pages share this name"


def test_strict_render_raises_and_default_warns(example_data):
    project = infer_project(example_data, "Ventes")
    project.pages = [Page("P", [_card(0, 0), _card(100, 0)])]
    with pytest.raises(LayoutError) as exc:
        render_project(project, strict=True)
    assert "overlaps" in str(exc.value)
    with pytest.warns(UserWarning, match="overlaps"):
        render_project(project)


def test_cli_strict_returns_error_on_bad_layout(example_data, tmp_path, monkeypatch, capsys):
    import pbip_generator.builder as builder

    monkeypatch.setattr(builder, "build_pages", lambda project: [Page("P", [_card(0, 0), _card(100, 0)])])
    assert main(["build", str(example_data), "-o", str(tmp_path), "--strict"]) == 1
    assert "overlaps" in capsys.readouterr().err


def test_slicer_label_is_in_header_and_container_title_hidden(example_data):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        files = render_project(infer_project(example_data, "Ventes"))
    slicers = _visuals(files, "slicer")
    assert slicers
    for s in slicers:
        visual = s["visual"]
        title = visual["visualContainerObjects"]["title"][0]["properties"]
        assert title["show"]["expr"]["Literal"]["Value"] == "false"
        header = visual["objects"]["header"][0]["properties"]
        assert header["show"]["expr"]["Literal"]["Value"] == "true"
        assert header["text"]["expr"]["Literal"]["Value"].startswith("'")
        assert visual["objects"]["data"][0]["properties"]["mode"]["expr"]["Literal"]["Value"] == "'Dropdown'"


def test_titled_card_hides_its_category_label(example_data):
    cards = _visuals(render_project(infer_project(example_data, "Ventes")), "card")
    assert cards
    for c in cards:
        label = c["visual"]["objects"]["categoryLabels"][0]["properties"]["show"]
        assert label["expr"]["Literal"]["Value"] == "false"


def test_charts_only_use_readable_categories(example_data):
    project = infer_project(example_data, "Ventes")
    for page in build_pages(project):
        for v in page.visuals:
            limit = CHART_MAX_CATEGORIES.get(v.visual_type)
            if limit is None:
                continue
            (cat,) = v.roles["Category"]
            assert project.table(cat.table).column(cat.name).distinct_count <= limit
