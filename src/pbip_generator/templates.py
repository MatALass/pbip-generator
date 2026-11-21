"""Page templates: turn a PageSpec into a Page with computed positions.

Every page has the same frame, so a report reads the same way from page to page:

    +-----------------------------------------------------------+
    | Page title                      [slicer] [slicer] [slicer] |   header, 64 px
    | [KPI]        [KPI]        [KPI]        [KPI]               |   KPI row, 96 px (kpis_* templates)
    | body: the template's slots                                 |
    +-----------------------------------------------------------+
"""

from __future__ import annotations

from .layout import GAP, MARGIN, PAGE_H, PAGE_W
from .model import FieldRef, Highlight, MeasureFilter, Page, Project, TableRole, Visual
from .spec import CHART_TYPES, PageSpec, VisualSpec
from .validate import resolve

HEADER_H, KPI_H, SLICER_W = 64, 96, 220

Rect = tuple[float, float, float, float]


def _row(n: int, y: float, h: float) -> list[Rect]:
    w = (PAGE_W - 2 * MARGIN - (n - 1) * GAP) / n
    return [(MARGIN + i * (w + GAP), y, w, h) for i in range(n)]


def body_slots(template: str, top: float) -> list[Rect]:
    """Positions of the template's visuals, in the area below ``top``."""
    height = PAGE_H - MARGIN - top
    half = (height - GAP) / 2
    if template == "kpis_2x2":
        return _row(2, top, half) + _row(2, top + half + GAP, half)
    if template == "kpis_1_2":
        return _row(1, top, half) + _row(2, top + half + GAP, half)
    if template == "kpis_2":
        return _row(2, top, height)
    return _row(1, top, height)


def _ref(project: Project, text: str) -> FieldRef:
    ref, error = resolve(project, text)
    if ref is None:  # validate_spec runs first, so this is a programming error
        raise ValueError(error)
    return ref


def _visual(project: Project, spec: VisualSpec, rect: Rect, colors: dict[int, FieldRef]) -> Visual:
    x, y, w, h = rect
    if spec.type == "textbox":
        return Visual("textbox", {}, x, y, w, h, text=spec.text, text_size=spec.text_size)
    values = [_ref(project, v) for v in spec.values]
    sort_by, descending = None, spec.sort_descending
    if spec.type in CHART_TYPES:
        category = _ref(project, spec.category or "")
        roles = {"Category": [category], "Y": values}
        sort_by = values[0]
        if project.table(category.table).role == TableRole.DATE:
            # A time axis reads left to right, whatever the measure does.
            sort_by, descending = category, False
    elif spec.type == "pivotTable":
        rows = [_ref(project, r) for r in spec.rows]
        roles = {"Rows": rows, "Columns": [_ref(project, c) for c in spec.columns], "Values": values}
        if not roles["Columns"]:
            del roles["Columns"]
        # Ranked by the first measure, unless the rows are a time axis.
        time_rows = project.table(rows[0].table).role == TableRole.DATE
        sort_by, descending = (rows[0], False) if time_rows else (values[0], True)
    else:
        roles = {"Values": values}
        sort_by = next((v for v in values if v.is_measure), None)
    if spec.sort_by:
        sort_by, descending = _ref(project, spec.sort_by), spec.sort_descending
    highlights = [
        Highlight(_ref(project, hl.field), colors[id(hl)], hl.apply) for hl in spec.highlights if id(hl) in colors
    ]
    return Visual(
        spec.type,
        roles,
        x,
        y,
        w,
        h,
        title=spec.title,
        sort_by=sort_by,
        sort_descending=descending,
        highlights=highlights,
        totals=spec.totals,
        filters=[MeasureFilter(_ref(project, f.field), f.operator, f.value) for f in spec.filters],
    )


def compile_page(project: Project, spec: PageSpec, colors: dict[int, FieldRef] | None = None) -> Page:
    page = Page(spec.name)
    slicers = [_ref(project, s) for s in spec.slicers]
    slicers_w = len(slicers) * (SLICER_W + GAP)
    page.visuals.append(
        Visual("textbox", {}, MARGIN, MARGIN, PAGE_W - 2 * MARGIN - slicers_w, HEADER_H, text=spec.name, text_size=20)
    )
    for i, ref in enumerate(slicers):
        x = PAGE_W - MARGIN - (len(slicers) - i) * (SLICER_W + GAP) + GAP
        single = spec.slicers[i] in spec.single_select
        page.visuals.append(
            Visual("slicer", {"Values": [ref]}, x, MARGIN, SLICER_W, HEADER_H, title=ref.name, single_select=single)
        )
    top = MARGIN + HEADER_H + GAP
    if spec.template != "table":
        for text, (x, y, w, h) in zip(spec.kpis, _row(len(spec.kpis), top, KPI_H), strict=True):
            ref = _ref(project, text)
            page.visuals.append(Visual("card", {"Values": [ref]}, x, y, w, h, title=ref.name))
        top += KPI_H + GAP
    for visual, rect in zip(spec.visuals, body_slots(spec.template, top), strict=True):
        page.visuals.append(_visual(project, visual, rect, colors or {}))
    return page
