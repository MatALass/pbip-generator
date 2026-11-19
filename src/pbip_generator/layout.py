"""Automatic report layout: an overview page and a detail page."""

from __future__ import annotations

from .inference import is_key_like
from .model import DataType, FieldRef, Page, Project, Table, TableRole, Visual

PAGE_W, PAGE_H = 1280, 720
MARGIN, GAP = 16, 16


def _category_columns(project: Project, max_distinct: int = 50) -> list[FieldRef]:
    """Low-cardinality text columns, dimensions first, fewest values first."""
    candidates: list[tuple[int, int, FieldRef]] = []
    for t in project.tables:
        if t.role == TableRole.DATE:
            continue
        rank = 0 if t.role == TableRole.DIMENSION else 1
        for c in t.columns:
            if c.data_type != DataType.STRING or c.is_hidden or is_key_like(c.name):
                continue
            if 2 <= c.distinct_count <= max_distinct:
                candidates.append((rank, c.distinct_count, FieldRef(t.name, c.name)))
    candidates.sort(key=lambda x: (x[0], x[1]))
    return [f for _, _, f in candidates]


def _label_columns(project: Project) -> list[FieldRef]:
    """Descriptive columns for the detail table (names, labels)."""
    out = []
    for t in project.tables:
        if t.role != TableRole.DIMENSION:
            continue
        for c in t.columns:
            if c.data_type == DataType.STRING and not c.is_hidden and not is_key_like(c.name):
                out.append(FieldRef(t.name, c.name))
    return out


def _measure_refs(project: Project) -> tuple[list[FieldRef], FieldRef | None, FieldRef | None]:
    """(base measures, primary measure, variation measure).

    Base measures are the automatic ones (folder "Base") and those without a folder. When there
    are none, for example with ``auto_measures: false`` and every custom measure in its own
    folder, the custom measures are used instead, so the report is never left without pages.
    """
    base, custom, variation = [], [], None
    for t, m in project.all_measures():
        ref = FieldRef(t.name, m.name, is_measure=True)
        if m.display_folder == "Base" or m.display_folder is None:
            base.append(ref)
        elif m.name.endswith("Var % N-1"):
            variation = variation or ref
        elif m.display_folder != "Temps":
            custom.append(ref)
    base = base or custom
    primary = base[0] if base else None
    return base, primary, variation


def _row(n: int, y: float, h: float) -> list[tuple[float, float, float, float]]:
    w = (PAGE_W - 2 * MARGIN - (n - 1) * GAP) / n
    return [(MARGIN + i * (w + GAP), y, w, h) for i in range(n)]


def _slicers(project: Project, categories: list[FieldRef]) -> list[Visual]:
    fields: list[FieldRef] = []
    cal = project.date_table
    if cal is not None and cal.source.kind == "date":
        fields.append(FieldRef(cal.name, "Année"))
    fields += categories[: 3 - len(fields)]
    if not fields:
        return []
    width = 280
    return [
        Visual("slicer", {"Values": [f]}, MARGIN + i * (width + GAP), MARGIN, width, 64, title=f.name)
        for i, f in enumerate(fields)
    ]


def build_pages(project: Project) -> list[Page]:
    base, primary, variation = _measure_refs(project)
    if primary is None:
        return []
    categories = _category_columns(project)
    cal: Table | None = project.date_table
    slicers = _slicers(project, categories)
    top = MARGIN + (64 + GAP if slicers else 0)

    overview = Page("Vue d'ensemble")
    overview.visuals += slicers

    kpis = base[:4]
    if variation is not None and len(kpis) < 4:
        kpis.append(variation)
    for ref, (x, y, w, h) in zip(kpis, _row(len(kpis), top, 112), strict=True):
        overview.visuals.append(Visual("card", {"Values": [ref]}, x, y, w, h, title=ref.name))

    charts_top = top + 112 + GAP
    chart_h = (PAGE_H - charts_top - MARGIN - GAP) / 2
    slots = _row(2, charts_top, chart_h) + _row(2, charts_top + chart_h + GAP, chart_h)
    charts: list[Visual] = []
    if cal is not None and cal.source.kind == "date":
        month = FieldRef(cal.name, "Année-Mois")
        charts.append(
            Visual(
                "lineChart",
                {"Category": [month], "Y": [primary]},
                0,
                0,
                0,
                0,
                title=f"{primary.name} par mois",
                sort_by=month,
                sort_descending=False,
            )
        )
    kinds = ["clusteredColumnChart", "clusteredBarChart", "donutChart"]
    for kind, cat in zip(kinds, categories, strict=False):
        charts.append(
            Visual(
                kind,
                {"Category": [cat], "Y": [primary]},
                0,
                0,
                0,
                0,
                title=f"{primary.name} par {cat.name}",
                sort_by=primary,
            )
        )
    for visual, (x, y, w, h) in zip(charts[:4], slots, strict=False):
        visual.x, visual.y, visual.width, visual.height = x, y, w, h
        overview.visuals.append(visual)

    detail = Page("Détail")
    detail.visuals += [Visual(v.visual_type, v.roles, v.x, v.y, v.width, v.height, title=v.title) for v in slicers]
    table_fields = _label_columns(project)[:4] + base[:4]
    detail.visuals.append(
        Visual(
            "tableEx",
            {"Values": table_fields},
            MARGIN,
            top,
            PAGE_W - 2 * MARGIN,
            PAGE_H - top - MARGIN,
            title="Détail",
            sort_by=primary,
        )
    )
    return [overview, detail]
