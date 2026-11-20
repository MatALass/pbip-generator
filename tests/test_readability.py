"""What a business reader needs to trust a page: currencies, meaningful N-1, full tables, readable titles."""

from __future__ import annotations

import json

import pytest

from pbip_generator import infer_project, render_project
from pbip_generator.inference import currency_format, is_money_like
from pbip_generator.model import FieldRef, Page, Visual
from pbip_generator.pbir import TABLE_CHROME, TITLE_COLOR


def _visuals(files: dict[str, str], visual_type: str) -> list[dict]:
    out = []
    for path, text in files.items():
        if path.endswith("visual.json"):
            data = json.loads(text)
            if data["visual"]["visualType"] == visual_type:
                out.append(data["visual"])
    return out


@pytest.mark.parametrize(
    ("name", "expected"),
    [("Montant", True), ("Prix unitaire", True), ("CA HT", True), ("Coût", True), ("Quantité", False),
     ("Catégorie", False), ("Nb ventes", False)],
)  # fmt: skip
def test_money_columns(name, expected):
    assert is_money_like(name) is expected


def test_currency_by_culture():
    assert currency_format("fr-FR", False) == "#,##0 €"
    assert currency_format("en-US", True) == "$#,##0.00"
    assert currency_format("ja-JP", False) == "#,##0"


def test_amounts_carry_their_currency(example_data):
    project = infer_project(example_data, "Ventes")
    ventes = project.table("Ventes")
    assert ventes.column("Montant").format_string == "#,##0.00 €"
    assert ventes.column("Quantité").format_string == "#,##0"
    measures = {m.name: m for m in ventes.measures}
    assert measures["Total Montant"].format_string == "#,##0 €"
    assert measures["Total Montant N-1"].format_string == "#,##0 €"
    assert measures["Total Quantité"].format_string == "#,##0"


def test_last_year_is_blank_over_more_than_a_year(example_data):
    measures = {m.name: m for m in infer_project(example_data, "Ventes").table("Ventes").measures}
    guard = "DATEDIFF(MIN(Calendrier[Date]), MAX(Calendrier[Date]), DAY) < 366"
    assert guard in measures["Total Montant N-1"].expression


def _project_with(example_data, visual: Visual):
    project = infer_project(example_data, "Ventes")
    project.pages = [Page("P", [visual])]
    return project


def test_table_columns_fill_the_visual(example_data):
    refs = [FieldRef("Clients", "Nom client"), FieldRef("Ventes", "Total Montant", is_measure=True)]
    project = _project_with(example_data, Visual("tableEx", {"Values": refs}, 0, 0, 640, 400, title="T"))
    (table,) = _visuals(render_project(project), "tableEx")
    widths = table["objects"]["columnWidth"]
    assert [w["selector"]["metadata"] for w in widths] == ["Clients.Nom client", "Ventes.Total Montant"]
    assert {w["properties"]["value"]["expr"]["Literal"]["Value"] for w in widths} == {f"{(640 - TABLE_CHROME) / 2}D"}


def test_donut_shows_percentages_without_legend(example_data):
    roles = {"Category": [FieldRef("Clients", "Segment")], "Y": [FieldRef("Ventes", "Total Montant", is_measure=True)]}
    project = _project_with(example_data, Visual("donutChart", roles, 0, 0, 400, 300, title="D"))
    (donut,) = _visuals(render_project(project), "donutChart")
    labels = donut["objects"]["labels"][0]["properties"]
    assert labels["labelStyle"]["expr"]["Literal"]["Value"] == "'Category, percent of total'"
    assert donut["objects"]["legend"][0]["properties"]["show"]["expr"]["Literal"]["Value"] == "false"


def test_titles_are_dark_unless_a_theme_is_set(example_data):
    measure = FieldRef("Ventes", "Total Montant", is_measure=True)
    card = Visual("card", {"Values": [measure]}, 0, 0, 300, 100, title="CA")
    project = _project_with(example_data, card)
    title = _visuals(render_project(project), "card")[0]["visualContainerObjects"]["title"][0]["properties"]
    assert title["fontColor"]["solid"]["color"]["expr"]["Literal"]["Value"] == f"'{TITLE_COLOR}'"
    project.theme = {"name": "Maison"}
    title = _visuals(render_project(project), "card")[0]["visualContainerObjects"]["title"][0]["properties"]
    assert "fontColor" not in title
