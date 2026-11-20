"""Layout checks: catch visuals that overlap, leave the page or are too small to show their data.

Power BI opens such a report without any error, so a broken layout is only seen once the project
is open in Desktop. These checks run at generation time instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Page, Project, Visual

# Smallest size (width, height) at which a visual still shows its data, title included.
# A dropdown slicer needs its header and its box: below ~56 px only the header is drawn.
MIN_SIZE: dict[str, tuple[float, float]] = {
    "slicer": (120, 56),
    "card": (120, 80),
    "textbox": (60, 32),
    "tableEx": (240, 140),
    "pivotTable": (240, 140),
    "lineChart": (240, 160),
    "clusteredColumnChart": (240, 160),
    "clusteredBarChart": (240, 160),
    "donutChart": (200, 160),
    "pieChart": (200, 160),
    "scatterChart": (240, 180),
}
DEFAULT_MIN_SIZE = (160, 120)

# Rounding noise from computed layouts (column widths divided by n).
TOLERANCE = 0.5


@dataclass(frozen=True)
class LayoutIssue:
    page: str
    visual: str
    message: str

    def __str__(self) -> str:
        return f"[{self.page}] {self.visual}: {self.message}"


class LayoutError(ValueError):
    """Raised by strict generation when the report layout has issues."""

    def __init__(self, issues: list[LayoutIssue]) -> None:
        self.issues = issues
        super().__init__("Report layout issues:\n" + "\n".join(f"  - {i}" for i in issues))


def _label(v: Visual, index: int) -> str:
    first = next((r.name for refs in v.roles.values() for r in refs), None)
    return f"#{index} {v.visual_type} '{v.title or v.text or first or '?'}'"


def _overlap(a: Visual, b: Visual) -> bool:
    return (
        a.x + a.width - TOLERANCE > b.x
        and b.x + b.width - TOLERANCE > a.x
        and a.y + a.height - TOLERANCE > b.y
        and b.y + b.height - TOLERANCE > a.y
    )


def check_page(page: Page) -> list[LayoutIssue]:
    issues: list[LayoutIssue] = []

    def add(index: int, v: Visual, message: str) -> None:
        issues.append(LayoutIssue(page.display_name, _label(v, index), message))

    for i, v in enumerate(page.visuals):
        if v.x < -TOLERANCE or v.y < -TOLERANCE:
            add(i, v, f"starts outside the page (x={v.x:g}, y={v.y:g})")
        if v.x + v.width > page.width + TOLERANCE or v.y + v.height > page.height + TOLERANCE:
            add(i, v, f"ends outside the {page.width}x{page.height} page")
        min_w, min_h = MIN_SIZE.get(v.visual_type, DEFAULT_MIN_SIZE)
        if v.width < min_w - TOLERANCE or v.height < min_h - TOLERANCE:
            add(i, v, f"{v.width:g}x{v.height:g} is too small, its data is cut (minimum {min_w:g}x{min_h:g})")
        if v.visual_type != "textbox" and not any(v.roles.values()):
            add(i, v, "has no field")
    for i, a in enumerate(page.visuals):
        for j in range(i + 1, len(page.visuals)):
            b = page.visuals[j]
            if _overlap(a, b):
                add(j, b, f"overlaps {_label(a, i)}")
    return issues


def check_pages(pages: list[Page]) -> list[LayoutIssue]:
    issues: list[LayoutIssue] = []
    names = [p.display_name for p in pages]
    for name in sorted({n for n in names if names.count(n) > 1}):
        issues.append(LayoutIssue(name, "page", "several pages share this name"))
    for page in pages:
        issues += check_page(page)
    return issues


def check_project(project: Project) -> list[LayoutIssue]:
    """Layout issues of the pages that would be generated for ``project``."""
    from .layout import build_pages

    return check_pages(project.pages or build_pages(project))
