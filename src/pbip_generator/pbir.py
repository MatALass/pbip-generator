"""Render the report in the PBIR format and the PBIP wrapper files."""

from __future__ import annotations

import json
import re
from typing import Any

from .ids import stable_name, stable_uuid
from .model import FieldRef, MeasureFilter, Page, Project, Visual

_BASE = "https://developer.microsoft.com/json-schemas/fabric"
SCHEMAS = {
    "pbip": f"{_BASE}/pbip/pbipProperties/1.0.0/schema.json",
    "pbir": f"{_BASE}/item/report/definitionProperties/2.0.0/schema.json",
    "pbism": f"{_BASE}/item/semanticModel/definitionProperties/1.0.0/schema.json",
    "platform": f"{_BASE}/gitIntegration/platformProperties/2.0.0/schema.json",
    "version": f"{_BASE}/item/report/definition/versionMetadata/1.0.0/schema.json",
    "report": f"{_BASE}/item/report/definition/report/2.0.0/schema.json",
    "pages": f"{_BASE}/item/report/definition/pagesMetadata/1.0.0/schema.json",
    "page": f"{_BASE}/item/report/definition/page/2.0.0/schema.json",
    "visual": f"{_BASE}/item/report/definition/visualContainer/2.0.0/schema.json",
}


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def _literal(value: str | bool | int | float) -> dict:
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (int, float)):
        text = f"{value}D"
    else:
        text = "'" + value.replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": text}}}


# --------------------------------------------------------------------------- #
# Wrapper files
# --------------------------------------------------------------------------- #
def render_pbip(project: Project) -> str:
    return dumps(
        {
            "$schema": SCHEMAS["pbip"],
            "version": "1.0",
            "artifacts": [{"report": {"path": f"{project.name}.Report"}}],
            "settings": {"enableAutoRecovery": True},
        }
    )


def render_platform(project: Project, item_type: str) -> str:
    return dumps(
        {
            "$schema": SCHEMAS["platform"],
            "metadata": {"type": item_type, "displayName": project.name},
            "config": {"version": "2.0", "logicalId": stable_uuid(project.name, item_type)},
        }
    )


def render_pbir(project: Project) -> str:
    return dumps(
        {
            "$schema": SCHEMAS["pbir"],
            "version": "4.0",
            "datasetReference": {"byPath": {"path": f"../{project.name}.SemanticModel"}},
        }
    )


def render_pbism() -> str:
    return dumps({"$schema": SCHEMAS["pbism"], "version": "4.0", "settings": {}})


# --------------------------------------------------------------------------- #
# Report definition
# --------------------------------------------------------------------------- #
def _field(ref: FieldRef) -> dict:
    kind = "Measure" if ref.is_measure else "Column"
    return {kind: {"Expression": {"SourceRef": {"Entity": ref.table}}, "Property": ref.name}}


def _projection(ref: FieldRef) -> dict:
    return {
        "field": _field(ref),
        "queryRef": f"{ref.table}.{ref.name}",
        "nativeQueryRef": ref.name,
    }


# Version of Power BI Desktop recorded with an imported theme. Desktop only uses it to
# migrate very old themes, any recent value works.
THEME_REPORT_VERSION = "5.55"


def theme_file_name(project: Project) -> str:
    raw = str((project.theme or {}).get("name") or project.name)
    return re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_") + ".json"


def render_static_resources(project: Project) -> dict[str, str]:
    """Files of ``<Name>.Report/StaticResources`` (the custom theme, if any)."""
    if not project.theme:
        return {}
    return {f"RegisteredResources/{theme_file_name(project)}": dumps(project.theme)}


def _textbox(project: Project, v: Visual) -> dict[str, Any]:
    style: dict[str, Any] = {"fontWeight": "bold", "fontSize": f"{v.text_size}pt"}
    if project.palette is not None:
        style["color"] = project.palette.text  # text runs ignore the theme: black on a dark page otherwise
    run = {"value": v.text or "", "textStyle": style}
    return {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": [{"textRuns": [run]}]}}]}}


def render_visual(project: Project, page_id: str, index: int, v: Visual) -> tuple[str, str]:
    name = stable_name(project.name, page_id, str(index), v.visual_type)
    if v.visual_type == "textbox":
        return name, dumps(_container(name, index, v, _textbox(project, v)))
    query: dict[str, Any] = {
        "queryState": {role: {"projections": [_projection(r) for r in refs]} for role, refs in v.roles.items()}
    }
    if v.sort_by is not None:
        query["sortDefinition"] = {
            "sort": [
                {
                    "field": _field(v.sort_by),
                    "direction": "Descending" if v.sort_descending else "Ascending",
                }
            ],
            "isDefaultSort": True,
        }
    visual: dict[str, Any] = {"visualType": v.visual_type, "query": query}
    if v.visual_type == "slicer":
        visual["objects"] = _slicer_objects(v)
        # The label lives in the slicer header (see _slicer_objects). A container title on top
        # of it, which themes often switch on for every visual, would push the dropdown box out
        # of a short slicer: only the title and the column name would be drawn.
        visual["visualContainerObjects"] = {"title": [{"properties": {"show": _literal(False)}}]}
        return name, dumps(_container(name, index, v, visual))
    visual["drillFilterOtherVisuals"] = True
    objects: dict[str, Any] = {}
    if v.visual_type == "card" and v.title:
        # The title already names the measure: the category label under the value would repeat
        # it and squeeze the value in a short card.
        objects["categoryLabels"] = [{"properties": {"show": _literal(False)}}]
    if v.visual_type == "tableEx":
        objects["columnWidth"] = _column_widths(v)
        if not v.totals:
            objects["total"] = [{"properties": {"totals": _literal(False)}}]
    if v.visual_type == "pivotTable" and not v.totals:
        objects["subTotals"] = [{"properties": {"rowSubtotals": _literal(False), "columnSubtotals": _literal(False)}}]
    if v.visual_type in ("donutChart", "pieChart"):
        # A donut is read in shares: label each slice with its category and percentage, which
        # makes the legend redundant.
        objects["labels"] = [
            {"properties": {"show": _literal(True), "labelStyle": _literal("Category, percent of total")}}
        ]
        objects["legend"] = [{"properties": {"show": _literal(False)}}]
    for h in v.highlights:
        color = {"solid": {"color": {"expr": _field(h.color)}}}
        if v.visual_type == "card":
            objects["labels"] = [{"properties": {"color": color}}]
        else:
            prop = "backColor" if h.apply == "background" else "fontColor"
            objects.setdefault("values", []).append(
                {
                    "properties": {prop: color},
                    "selector": {
                        "data": [{"dataViewWildcard": {"matchingOption": 1}}],
                        "metadata": f"{h.target.table}.{h.target.name}",
                    },
                }
            )
    if objects:
        visual["objects"] = objects
    if v.title:
        title: dict[str, Any] = {"show": _literal(True), "text": _literal(v.title)}
        if project.theme is None:
            # The default theme draws titles in light grey, too pale to read at a glance.
            title["fontColor"] = {"solid": {"color": _literal(TITLE_COLOR)}}
            title["fontSize"] = _literal(TITLE_SIZE)
        visual["visualContainerObjects"] = {"title": [{"properties": title}]}
    return name, dumps(_container(name, index, v, visual))


TITLE_COLOR, TITLE_SIZE = "#252423", 12
# Room taken by the table's borders and vertical scrollbar, not available to the columns.
TABLE_CHROME = 40


def _column_widths(v: Visual) -> list[dict[str, Any]]:
    """Share the table's width between its columns, so it fills its slot instead of leaving it
    mostly empty (Power BI sizes columns to their content by default)."""
    refs = [r for refs in v.roles.values() for r in refs]
    width = max(v.width - TABLE_CHROME, 0) / max(len(refs), 1)
    return [
        {"properties": {"value": _literal(round(width, 1))}, "selector": {"metadata": f"{r.table}.{r.name}"}}
        for r in refs
    ]


def _slicer_objects(v: Visual) -> dict[str, Any]:
    header: dict[str, Any] = {"show": _literal(True)}
    if v.title:
        header["text"] = _literal(v.title)
    objects: dict[str, Any] = {
        "data": [{"properties": {"mode": _literal("Dropdown")}}],
        "header": [{"properties": header}],
    }
    if v.single_select:
        objects["selection"] = [{"properties": {"singleSelect": _literal(True), "strictSingleSelect": _literal(True)}}]
    return objects


# ComparisonKind of the semantic query language.
_COMPARISON = {"=": 0, ">": 1, ">=": 2, "<": 3, "<=": 4}


def _measure_filter(visual_name: str, index: int, f: MeasureFilter) -> dict[str, Any]:
    """An 'Advanced' visual-level filter, written as Power BI Desktop writes one ('is greater than or
    equal to 5' in the filter pane). Evaluated per row of the visual, like any visual filter."""
    value = f"{int(f.value)}L" if float(f.value).is_integer() else f"{f.value}D"
    alias = "t"
    return {
        "name": stable_name(visual_name, "filter", str(index)),
        "field": _field(f.measure),
        "type": "Advanced",
        "filter": {
            "Version": 2,
            "From": [{"Name": alias, "Entity": f.measure.table, "Type": 0}],
            "Where": [
                {
                    "Condition": {
                        "Comparison": {
                            "ComparisonKind": _COMPARISON[f.operator],
                            "Left": {
                                "Measure": {"Expression": {"SourceRef": {"Source": alias}}, "Property": f.measure.name}
                            },
                            "Right": {"Literal": {"Value": value}},
                        }
                    }
                }
            ],
        },
        "howCreated": "User",
    }


def _container(name: str, index: int, v: Visual, visual: dict[str, Any]) -> dict[str, Any]:
    container: dict[str, Any] = {
        "$schema": SCHEMAS["visual"],
        "name": name,
        "position": {
            "x": round(v.x, 2),
            "y": round(v.y, 2),
            "z": index * 1000,
            "width": round(v.width, 2),
            "height": round(v.height, 2),
            "tabOrder": index * 1000,
        },
        "visual": visual,
    }
    if v.filters:
        container["filterConfig"] = {"filters": [_measure_filter(name, i, f) for i, f in enumerate(v.filters)]}
    return container


def render_report_json(project: Project) -> dict[str, Any]:
    report: dict[str, Any] = {"$schema": SCHEMAS["report"], "themeCollection": {}}
    if project.theme:
        file_name = theme_file_name(project)
        report["themeCollection"]["customTheme"] = {
            "name": file_name,
            "reportVersionAtImport": THEME_REPORT_VERSION,
            "type": "RegisteredResources",
        }
        report["resourcePackages"] = [
            {
                "name": "RegisteredResources",
                "type": "RegisteredResources",
                "items": [{"name": file_name, "path": file_name, "type": "CustomTheme"}],
            }
        ]
    report["settings"] = {
        "useStylableVisualContainerHeader": True,
        "defaultDrillFilterOtherVisuals": True,
        # Clicking a row filters the other visuals instead of highlighting them: a highlighted
        # chart draws nothing when its measure is blank without the selection (rates per item).
        "defaultFilterActionIsDataFilter": True,
        "allowChangeFilterTypes": True,
        "useEnhancedTooltips": True,
    }
    return report


def render_report_definition(project: Project, pages: list[Page]) -> dict[str, str]:
    files = {
        "version.json": dumps({"$schema": SCHEMAS["version"], "version": "2.0.0"}),
        "report.json": dumps(render_report_json(project)),
    }
    page_ids = []
    for page_index, page in enumerate(pages):
        page_id = stable_name(project.name, "page", str(page_index), page.display_name)
        page_ids.append(page_id)
        files[f"pages/{page_id}/page.json"] = dumps(
            {
                "$schema": SCHEMAS["page"],
                "name": page_id,
                "displayName": page.display_name,
                "displayOption": "FitToPage",
                "height": page.height,
                "width": page.width,
            }
        )
        for i, visual in enumerate(page.visuals):
            vid, content = render_visual(project, page_id, i, visual)
            files[f"pages/{page_id}/visuals/{vid}/visual.json"] = content
    files["pages/pages.json"] = dumps(
        {
            "$schema": SCHEMAS["pages"],
            "pageOrder": page_ids,
            "activePageName": page_ids[0] if page_ids else "",
        }
    )
    return files
