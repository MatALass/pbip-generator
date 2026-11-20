"""In-memory description of a Power BI project (semantic model + report).

Everything the renderers need lives here, so inference, YAML overrides and
rendering stay fully decoupled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .themes import Palette


class DataType(str, Enum):
    """Tabular data types, named as in TMDL."""

    STRING = "string"
    INT64 = "int64"
    DOUBLE = "double"
    DATETIME = "dateTime"
    BOOLEAN = "boolean"


class TableRole(str, Enum):
    FACT = "fact"
    DIMENSION = "dimension"
    DATE = "date"


@dataclass
class Column:
    name: str
    data_type: DataType
    source_column: str | None = None
    is_date_only: bool = False  # dateTime column holding dates only
    is_key: bool = False
    is_hidden: bool = False
    summarize_by: str = "none"
    format_string: str | None = None
    sort_by_column: str | None = None
    distinct_count: int = 0
    is_unique: bool = False
    years: tuple[int, int] | None = None  # first and last year of a dateTime column

    def __post_init__(self) -> None:
        if self.source_column is None:
            self.source_column = self.name


@dataclass
class Measure:
    name: str
    expression: str
    format_string: str | None = None
    display_folder: str | None = None
    description: str | None = None
    is_hidden: bool = False


@dataclass
class Source:
    """Where a table's rows come from."""

    kind: str  # "csv" | "excel" | "date"
    file_name: str = ""
    sheet: str | None = None
    delimiter: str = ","
    encoding: int = 65001
    culture: str = "en-US"


@dataclass
class Table:
    name: str
    columns: list[Column]
    source: Source
    role: TableRole = TableRole.DIMENSION
    measures: list[Measure] = field(default_factory=list)
    row_count: int = 0

    def column(self, name: str) -> Column:
        for col in self.columns:
            if col.name == name:
                return col
        raise KeyError(f"Column '{name}' not found in table '{self.name}'")

    def has_column(self, name: str) -> bool:
        return any(c.name == name for c in self.columns)


@dataclass
class Relationship:
    from_table: str  # many side
    from_column: str
    to_table: str  # one side
    to_column: str
    is_active: bool = True
    date_part_only: bool = False


@dataclass
class FieldRef:
    """Reference to a column or a measure, used by visuals."""

    table: str
    name: str
    is_measure: bool = False


@dataclass
class Highlight:
    """Color one field of a visual with a measure returning '#RRGGBB' (a table cell, a card value)."""

    target: FieldRef
    color: FieldRef  # the color measure
    apply: str = "background"  # "background" | "font"


@dataclass
class Visual:
    visual_type: str
    roles: dict[str, list[FieldRef]]
    x: float
    y: float
    width: float
    height: float
    title: str | None = None
    sort_by: FieldRef | None = None
    sort_descending: bool = True
    text: str | None = None  # textbox content (visual_type "textbox")
    text_size: int = 20  # textbox font size, in points
    highlights: list[Highlight] = field(default_factory=list)
    totals: bool = True  # total row of a table
    single_select: bool = False  # slicer that takes exactly one value


@dataclass
class Page:
    display_name: str
    visuals: list[Visual] = field(default_factory=list)
    width: int = 1280
    height: int = 720


@dataclass
class Project:
    name: str
    tables: list[Table]
    relationships: list[Relationship] = field(default_factory=list)
    pages: list[Page] = field(default_factory=list)
    culture: str = "fr-FR"
    data_folder: str = ""  # value of the DataFolder Power Query parameter
    source_dir: Path | None = None
    theme: dict | None = None  # Power BI report theme (the JSON you would import in Desktop)
    palette: Palette | None = None  # colors of a built-in theme, for the text the theme cannot style

    def table(self, name: str) -> Table:
        for t in self.tables:
            if t.name == name:
                return t
        raise KeyError(f"Table '{name}' not found")

    def has_table(self, name: str) -> bool:
        return any(t.name == name for t in self.tables)

    @property
    def facts(self) -> list[Table]:
        return [t for t in self.tables if t.role == TableRole.FACT]

    @property
    def date_table(self) -> Table | None:
        return next((t for t in self.tables if t.role == TableRole.DATE), None)

    def all_measures(self) -> list[tuple[Table, Measure]]:
        return [(t, m) for t in self.tables for m in t.measures]
