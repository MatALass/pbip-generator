"""Built-in report themes: a palette turned into a complete Power BI theme JSON.

A theme is where most of a report's look lives: page and card backgrounds, rounded borders and
shadows, title and table styles, chart colors. Every visual reads it, so no visual needs its own
colors. The same palette also names the colors a spec can use to highlight values
(``good``, ``neutral``, ``bad``, ``accent``...), turned into DAX color measures.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass(frozen=True)
class Palette:
    page: str  # page background
    surface: str  # visual background
    header: str  # table header and total rows
    stripe: str  # alternate table rows
    border: str
    text: str
    muted: str  # labels, axes, slicer headers
    accent: str  # KPI values, first chart color
    secondary: str
    good: str
    neutral: str
    bad: str
    shadow_transparency: int
    extra_colors: tuple[str, ...]

    @property
    def data_colors(self) -> list[str]:
        return [self.accent, self.secondary, *self.extra_colors]

    def color(self, name: str) -> str:
        """A palette color by name ('good', 'accent'...) or a '#RRGGBB' value."""
        if HEX.match(name):
            return name.upper()
        if name not in COLOR_NAMES:
            raise ValueError(f"Unknown color '{name}', expected one of {', '.join(COLOR_NAMES)} or '#RRGGBB'")
        return getattr(self, name)


COLOR_NAMES = ("good", "neutral", "bad", "accent", "secondary", "muted", "text")

PRESETS = {
    "light": Palette(
        page="#F2F4F7",
        surface="#FFFFFF",
        header="#E8ECF3",
        stripe="#F7F9FC",
        border="#DDE2EA",
        text="#1E2633",
        muted="#677386",
        accent="#3B5BDB",
        secondary="#12B886",
        good="#12B886",
        neutral="#F59F00",
        bad="#E03131",
        shadow_transparency=85,
        extra_colors=("#F59F00", "#AE3EC9", "#1C7ED6", "#E8590C", "#868E96"),
    ),
    "dark": Palette(
        page="#0E1217",
        surface="#171D25",
        header="#212A35",
        stripe="#1B222B",
        border="#2A3441",
        text="#E6E9EF",
        muted="#8B95A5",
        accent="#FF5A5F",
        secondary="#2EC4B6",
        good="#3DDC97",
        neutral="#FFB547",
        bad="#FF5A5F",
        shadow_transparency=40,
        extra_colors=("#FFB547", "#7C83FD", "#3DDC97", "#F78FB3", "#4FC3F7"),
    ),
}


def palette_for(preset: str, accent: str | None = None, secondary: str | None = None) -> Palette:
    palette = PRESETS[preset]
    if accent:
        palette = replace(palette, accent=accent.upper())
    if secondary:
        palette = replace(palette, secondary=secondary.upper())
    return palette


def _solid(color: str) -> dict[str, Any]:
    return {"solid": {"color": color}}


def build_theme(name: str, p: Palette) -> dict[str, Any]:
    """The theme JSON, as Power BI Desktop imports it (View > Themes > Browse for themes)."""
    title = {"show": True, "fontColor": _solid(p.text), "fontSize": 12, "fontFamily": "Segoe UI Semibold"}
    return {
        "name": name,
        "dataColors": p.data_colors,
        "background": p.surface,
        "foreground": p.text,
        "tableAccent": p.accent,
        "good": p.good,
        "neutral": p.neutral,
        "bad": p.bad,
        "maximum": p.good,
        "center": p.neutral,
        "minimum": p.bad,
        "textClasses": {
            "callout": {"fontFace": "Segoe UI Semibold", "fontSize": 28, "color": p.accent},
            "title": {"fontFace": "Segoe UI Semibold", "fontSize": 12, "color": p.text},
            "header": {"fontFace": "Segoe UI Semibold", "fontSize": 12, "color": p.text},
            "label": {"fontFace": "Segoe UI", "fontSize": 10, "color": p.muted},
        },
        "visualStyles": {
            "*": {
                "*": {
                    # Every visual is a card on the page: its own background, rounded border, shadow.
                    "background": [{"show": True, "color": _solid(p.surface), "transparency": 0}],
                    "border": [{"show": True, "color": _solid(p.border), "radius": 10}],
                    "dropShadow": [
                        {
                            "show": True,
                            "color": _solid("#000000"),
                            "position": "Outer",
                            "preset": "Custom",
                            "shadowBlur": 10,
                            "shadowDistance": 2,
                            "shadowSpread": 0,
                            "transparency": p.shadow_transparency,
                        }
                    ],
                    "padding": [{"top": 8, "bottom": 8, "left": 12, "right": 12}],
                    "title": [title],
                    "visualHeader": [{"background": _solid(p.surface), "foreground": _solid(p.muted)}],
                    "categoryAxis": [{"labelColor": _solid(p.muted), "titleColor": _solid(p.muted)}],
                    "valueAxis": [
                        {
                            "labelColor": _solid(p.muted),
                            "titleColor": _solid(p.muted),
                            "gridlineColor": _solid(p.border),
                        }
                    ],
                    "legend": [{"labelColor": _solid(p.muted)}],
                    "labels": [{"color": _solid(p.text)}],
                }
            },
            "page": {
                "*": {
                    "background": [{"color": _solid(p.page), "transparency": 0}],
                    "outspace": [{"color": _solid(p.page), "transparency": 0}],
                }
            },
            "card": {
                "*": {
                    "labels": [{"color": _solid(p.accent), "fontSize": 30, "fontFamily": "Segoe UI Semibold"}],
                    "categoryLabels": [{"color": _solid(p.muted)}],
                }
            },
            "tableEx": {
                "*": {
                    "columnHeaders": [
                        {
                            "fontColor": _solid(p.text),
                            "backColor": _solid(p.header),
                            "fontFamily": "Segoe UI Semibold",
                            "fontSize": 10,
                        }
                    ],
                    "values": [
                        {
                            "fontColorPrimary": _solid(p.text),
                            "backColorPrimary": _solid(p.surface),
                            "fontColorSecondary": _solid(p.text),
                            "backColorSecondary": _solid(p.stripe),
                            "fontSize": 10,
                        }
                    ],
                    "grid": [
                        {
                            "gridHorizontal": True,
                            "gridHorizontalColor": _solid(p.border),
                            "outlineColor": _solid(p.accent),
                            "rowPadding": 4,
                        }
                    ],
                    "total": [{"fontColor": _solid(p.text), "backColor": _solid(p.header)}],
                }
            },
            "slicer": {
                "*": {
                    "header": [{"fontColor": _solid(p.muted), "fontSize": 10}],
                    "items": [{"fontColor": _solid(p.text), "background": _solid(p.surface)}],
                }
            },
            # Page titles sit on the page itself, not in a card.
            "textbox": {
                "*": {
                    "background": [{"show": False}],
                    "border": [{"show": False}],
                    "dropShadow": [{"show": False}],
                }
            },
        },
    }
