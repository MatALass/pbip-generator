"""ReportSpec: a typed description of the whole report (model overrides + pages).

It is the contract between whoever decides what the report shows (a person, or a language model)
and the deterministic code that writes the files. The spec only names things: tables, columns,
measures, page templates. Pixel positions, TMDL and PBIR are always produced by the code.

Field references are text:

- ``Table[Column]`` for a column, ``Table[Measure]`` or ``[Measure]`` for a measure.

Example (YAML or JSON)::

    name: Ventes
    business_question: Où se fait le chiffre d'affaires et comment évolue-t-il ?
    audience: direction
    measures:
      - table: Ventes
        name: Panier moyen
        expression: DIVIDE([Total Montant], [Nb Ventes])
        format: '#,##0.00 €'
        description: Montant moyen d'une vente
    pages:
      - name: Synthèse
        purpose: Voir en 10 secondes le CA, sa tendance et ses meilleurs segments
        template: kpis_1_2
        slicers: ['Calendrier[Année]', 'Clients[Région]']
        kpis: ['[Total Montant]', '[Panier moyen]']
        visuals:
          - {type: lineChart, title: CA par mois, category: 'Calendrier[Année-Mois]', values: ['[Total Montant]']}
          - ...

Every key of the spec is checked against the inferred model before anything is written, with
error messages that list what is available (see ``validate.py``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import ConfigError, ProjectConfig
from .errors import PbipGeneratorError
from .model import FieldRef, Measure, Project
from .themes import build_theme, palette_for

VisualType = Literal[
    "card", "lineChart", "clusteredColumnChart", "clusteredBarChart", "donutChart", "tableEx", "textbox"
]
Template = Literal["kpis_2x2", "kpis_1_2", "kpis_2", "kpis_table", "table"]

# Number of visuals each template holds (KPI cards excluded).
TEMPLATE_SLOTS = {"kpis_2x2": 4, "kpis_1_2": 3, "kpis_2": 2, "kpis_table": 1, "table": 1}
CHART_TYPES = {"lineChart", "clusteredColumnChart", "clusteredBarChart", "donutChart"}


class _Strict(BaseModel):
    # Unknown keys are errors: a typo must not be silently ignored.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TableOverride(_Strict):
    role: Literal["fact", "dimension", "date"] | None = None
    types: dict[str, Literal["string", "int64", "double", "dateTime", "boolean"]] = {}
    hide: list[str] = []
    key: str | None = Field(None, description="Unique date column, required with role 'date'")


class RelationshipRef(_Strict):
    from_: str = Field(alias="from", description="Many side, 'Table[Column]'")
    to: str = Field(description="One side, 'Table[Column]'")
    active: bool = True


class RelationshipChanges(_Strict):
    add: list[RelationshipRef] = []
    remove: list[RelationshipRef] = []


class MeasureSpec(_Strict):
    table: str = Field(description="Home table of the measure, usually the fact table")
    name: str
    expression: str = Field(description="DAX expression; use DIVIDE for ratios")
    format: str | None = Field(None, description="Format string, e.g. '#,##0 €' or '0.0 %'")
    folder: str = "KPI"
    description: str = Field(min_length=1, description="What the measure means, for a business reader")


class RuleSpec(_Strict):
    below: float = Field(description="Applies when the value is below this threshold (rules are read in order)")
    color: str = Field(description="good | neutral | bad | accent | secondary | muted | text | '#RRGGBB'")


class HighlightSpec(_Strict):
    field: str = Field(description="A measure of the visual's values, '[Measure]'")
    rules: list[RuleSpec] = Field(min_length=1, description="Increasing thresholds; first match wins")
    otherwise: str = Field(description="Color when no rule matches (same names as rules)")
    apply: Literal["background", "font"] = Field("background", description="Cell background or text (tables)")


class ThemeSpec(_Strict):
    preset: Literal["light", "dark"] = "light"
    accent: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$", description="Main color: KPI values, first series")
    secondary: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class VisualSpec(_Strict):
    type: VisualType
    title: str | None = Field(None, description="Required, except for textbox")
    category: str | None = Field(None, description="Axis column of a chart, 'Table[Column]'")
    values: list[str] = Field(default=[], description="Measures (charts, cards) or columns and measures (tableEx)")
    sort_by: str | None = Field(None, description="One of the visual's fields")
    sort_descending: bool = True
    text: str | None = Field(None, description="Content of a textbox")
    text_size: int = 14
    highlights: list[HighlightSpec] = Field(
        default=[], description="Color a measure by thresholds: table cells (tableEx) or the value (card)"
    )
    totals: bool = Field(True, description="Total row of a tableEx; turn off when its columns are ratios")


class PageSpec(_Strict):
    name: str
    purpose: str = Field(min_length=1, description="The question this page answers")
    template: Template = Field(
        description="kpis_2x2: KPI row + 4 visuals; kpis_1_2: KPI row + 1 wide + 2 visuals; "
        "kpis_2: KPI row + 2 visuals; kpis_table: KPI row + 1 full-width visual; table: 1 full-page visual"
    )
    slicers: list[str] = Field(default=[], max_length=3, description="Columns, 'Table[Column]'")
    single_select: list[str] = Field(default=[], description="Slicers of this page that take exactly one value")
    kpis: list[str] = Field(default=[], max_length=4, description="Measures shown as cards at the top")
    visuals: list[VisualSpec]


class ReportSpec(_Strict):
    name: str | None = None
    business_question: str = Field(min_length=1, description="What the report is for, in one sentence")
    audience: Literal["daf", "direction", "commercial", "operationnel"]
    culture: str = "fr-FR"
    date_table: bool = True
    auto_measures: bool = True
    auto_relationships: bool = True
    tables: dict[str, TableOverride] = {}
    relationships: RelationshipChanges = RelationshipChanges()
    measures: list[MeasureSpec] = []
    theme: ThemeSpec = Field(default_factory=ThemeSpec, description="Report look: light or dark, main colors")
    pages: list[PageSpec] = Field(min_length=1)

    # ------------------------------------------------------------------ #
    def to_config(self) -> ProjectConfig:
        """The model part of the spec, as the YAML config the inference already understands."""
        tables: dict[str, dict[str, Any]] = {
            name: override.model_dump(exclude_defaults=True) for name, override in self.tables.items()
        }
        for m in self.measures:
            tables.setdefault(m.table, {}).setdefault("measures", []).append(
                {
                    "name": m.name,
                    "expression": m.expression,
                    "format": m.format,
                    "folder": m.folder,
                    "description": m.description,
                }
            )
        relationships = {
            kind: [{"from": r.from_, "to": r.to, "active": r.active} for r in getattr(self.relationships, kind)]
            for kind in ("add", "remove")
        }
        return ProjectConfig(
            name=self.name,
            culture=self.culture,
            date_table=self.date_table,
            auto_measures=self.auto_measures,
            auto_relationships=self.auto_relationships,
            tables=tables,
            relationships=relationships,
        )


class SpecError(PbipGeneratorError, ValueError):
    """The spec cannot be read, or does not match the data."""

    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__("Report spec issues:\n" + "\n".join(f"  - {i}" for i in issues))


def parse_spec(data: dict[str, Any]) -> ReportSpec:
    try:
        return ReportSpec.model_validate(data)
    except ValidationError as exc:
        raise SpecError([f"{'.'.join(str(p) for p in e['loc']) or 'spec'}: {e['msg']}" for e in exc.errors()]) from exc


def load_spec(path: Path) -> ReportSpec:
    """Read a spec from a YAML or JSON file (YAML is a superset of JSON)."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SpecError([f"invalid YAML/JSON in {path}: {exc}"]) from exc
    if not isinstance(raw, dict):
        raise SpecError(["spec: the root must be a mapping"])
    return parse_spec(raw)


def spec_json_schema() -> dict[str, Any]:
    return ReportSpec.model_json_schema(by_alias=True)


def build_project_from_spec(
    data_dir: Path, spec: ReportSpec, name: str | None = None, data_folder: str | None = None
) -> Project:
    """Infer the model from the data, apply the spec, check it, and lay out its pages."""
    from .inference import infer_project
    from .templates import compile_page
    from .validate import validate_spec

    name = name or spec.name or Path(data_dir).resolve().name
    try:
        project = infer_project(Path(data_dir), name, data_folder, spec.to_config())
    except ConfigError as exc:
        raise SpecError([f"{exc} (tables: {', '.join(_table_names(data_dir))})"]) from exc
    issues = validate_spec(spec, project)
    if issues:
        raise SpecError(issues)
    project.palette = palette_for(spec.theme.preset, spec.theme.accent, spec.theme.secondary)
    project.theme = build_theme(f"{project.name} {spec.theme.preset}", project.palette)
    colors = _add_color_measures(project, spec)
    project.pages = [compile_page(project, page, colors) for page in spec.pages]
    return project


def _dax_number(value: float) -> str:
    """0.45 -> '0.45', 20000.0 -> '20000' (no exponent, which DAX would not read)."""
    return format(value, "f").rstrip("0").rstrip(".") or "0"


def _add_color_measures(project: Project, spec: ReportSpec) -> dict[int, FieldRef]:
    """One hidden DAX measure per highlight, returning the color of the current value.

    Colors are computed in the model, so they follow every filter and the visual only points at
    the measure. Returns {id(HighlightSpec): measure}.
    """
    from .validate import resolve

    palette = project.palette
    assert palette is not None
    out: dict[int, FieldRef] = {}
    defined: dict[str, str] = {}
    for page in spec.pages:
        for visual in page.visuals:
            for h in visual.highlights:
                target, _ = resolve(project, h.field)
                assert target is not None  # checked by validate_spec
                cases = "".join(f'    _v < {_dax_number(r.below)}, "{palette.color(r.color)}",\n' for r in h.rules)
                expression = (
                    f"VAR _v = [{target.name}]\nRETURN SWITCH(\n    TRUE(),\n    ISBLANK(_v), BLANK(),\n"
                    f'{cases}    "{palette.color(h.otherwise)}"\n)'
                )
                name, n = f"Couleur {target.name}", 1
                while name in defined and defined[name] != expression:
                    n += 1
                    name = f"Couleur {target.name} {n}"
                if name not in defined:
                    defined[name] = expression
                    project.table(target.table).measures.append(
                        Measure(
                            name,
                            expression,
                            display_folder="Couleurs",
                            is_hidden=True,
                            description=f"Couleur de mise en évidence de {target.name}",
                        )
                    )
                out[id(h)] = FieldRef(target.table, name, is_measure=True)
    return out


def _table_names(data_dir: Path) -> list[str]:
    from .inference import infer_project

    try:
        return [t.name for t in infer_project(Path(data_dir), "probe").tables]
    except (OSError, ValueError):
        return []
