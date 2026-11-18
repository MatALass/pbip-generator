"""Render the semantic model as TMDL files (``<Name>.SemanticModel/definition``)."""

from __future__ import annotations

import json
import re

from . import mquery
from .ids import stable_uuid
from .model import Column, DataType, Measure, Project, Relationship, Table, TableRole

TAB = "\t"
COMPATIBILITY_LEVEL = 1600
_SIMPLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def q(name: str) -> str:
    """Quote a TMDL object name when needed."""
    return name if _SIMPLE.match(name) else "'" + name.replace("'", "''") + "'"


def _expression_block(expression: str, indent: int) -> list[str]:
    pad = TAB * indent
    return [pad + line if line.strip() else "" for line in expression.splitlines()]


# --------------------------------------------------------------------------- #
def render_database() -> str:
    return f"database\n{TAB}compatibilityLevel: {COMPATIBILITY_LEVEL}\n"


def render_model(project: Project) -> str:
    query_order = [mquery.PARAMETER_NAME] + [t.name for t in project.tables]
    lines = [
        "model Model",
        f"{TAB}culture: {project.culture}",
        f"{TAB}defaultPowerBIDataSourceVersion: powerBI_V3",
        f"{TAB}sourceQueryCulture: {project.culture}",
        f"{TAB}dataAccessOptions",
        f"{TAB}{TAB}legacyRedirects",
        f"{TAB}{TAB}returnErrorValuesAsNull",
        "",
        "annotation __PBI_TimeIntelligenceEnabled = 0",
        "",
        f"annotation PBI_QueryOrder = {json.dumps(query_order, ensure_ascii=False)}",
        "",
    ]
    lines += [f"ref table {q(t.name)}" for t in project.tables]
    return "\n".join(lines) + "\n"


def render_expressions(project: Project) -> str:
    name = mquery.PARAMETER_NAME
    return "\n".join(
        [
            f"expression {name} = {mquery.parameter_expression(project)}",
            f"{TAB}lineageTag: {stable_uuid(project.name, 'expression', name)}",
            "",
            f"{TAB}annotation PBI_ResultType = Text",
            "",
        ]
    )


def _render_measure(project: Project, table: Table, m: Measure) -> list[str]:
    expr_lines = m.expression.strip().splitlines()
    if len(expr_lines) == 1:
        out = [f"{TAB}measure {q(m.name)} = {expr_lines[0]}"]
    else:
        out = [f"{TAB}measure {q(m.name)} ="] + _expression_block(m.expression.strip(), 3)
    if m.format_string:
        out.append(f"{TAB * 2}formatString: {m.format_string}")
    if m.display_folder:
        out.append(f"{TAB * 2}displayFolder: {m.display_folder}")
    out.append(f"{TAB * 2}lineageTag: {stable_uuid(project.name, table.name, 'measure', m.name)}")
    if m.description:
        # Descriptions are written as /// comments above the object in TMDL.
        out.insert(0, f"{TAB}/// {m.description}")
    out.append("")
    return out


def _render_column(project: Project, table: Table, c: Column) -> list[str]:
    out = [f"{TAB}column {q(c.name)}", f"{TAB * 2}dataType: {c.data_type.value}"]
    if c.format_string:
        out.append(f"{TAB * 2}formatString: {c.format_string}")
    if c.is_key:
        out.append(f"{TAB * 2}isKey")
    if c.is_hidden:
        out.append(f"{TAB * 2}isHidden")
    out.append(f"{TAB * 2}lineageTag: {stable_uuid(project.name, table.name, 'column', c.name)}")
    out.append(f"{TAB * 2}summarizeBy: {c.summarize_by}")
    out.append(f"{TAB * 2}sourceColumn: {c.source_column}")
    if c.sort_by_column:
        out.append(f"{TAB * 2}sortByColumn: {q(c.sort_by_column)}")
    out.append("")
    out.append(f"{TAB * 2}annotation SummarizationSetBy = Automatic")
    if c.data_type == DataType.DATETIME and c.is_date_only:
        out.append("")
        out.append(f"{TAB * 2}annotation UnderlyingDateTimeDataType = Date")
    out.append("")
    return out


def render_table(project: Project, table: Table) -> str:
    lines = [f"table {q(table.name)}"]
    if table.role == TableRole.DATE:
        lines.append(f"{TAB}dataCategory: Time")
    lines.append(f"{TAB}lineageTag: {stable_uuid(project.name, 'table', table.name)}")
    lines.append("")
    for m in table.measures:
        lines += _render_measure(project, table, m)
    for c in table.columns:
        lines += _render_column(project, table, c)
    lines.append(f"{TAB}partition {q(table.name)} = m")
    lines.append(f"{TAB * 2}mode: import")
    lines.append(f"{TAB * 2}source =")
    lines += _expression_block(mquery.table_expression(project, table), 4)
    lines.append("")
    lines.append(f"{TAB}annotation PBI_ResultType = Table")
    return "\n".join(lines) + "\n"


def _column_ref(table: str, column: str) -> str:
    return f"{q(table)}.{q(column)}"


def render_relationships(project: Project) -> str:
    blocks = []
    for r in project.relationships:
        blocks.append(_render_relationship(project, r))
    return "\n".join(blocks)


def _render_relationship(project: Project, r: Relationship) -> str:
    rid = stable_uuid(project.name, "rel", r.from_table, r.from_column, r.to_table, r.to_column)
    lines = [f"relationship {rid}"]
    if not r.is_active:
        lines.append(f"{TAB}isActive: false")
    if r.date_part_only:
        lines.append(f"{TAB}joinOnDateBehavior: datePartOnly")
    lines.append(f"{TAB}fromColumn: {_column_ref(r.from_table, r.from_column)}")
    lines.append(f"{TAB}toColumn: {_column_ref(r.to_table, r.to_column)}")
    return "\n".join(lines) + "\n"


def table_file_name(table: Table) -> str:
    """File name for a table: Windows-safe, keeps the table name readable."""
    return re.sub(r'[<>:"/\\|?*]', "_", table.name) + ".tmdl"


def render_definition(project: Project) -> dict[str, str]:
    """Return {relative path: content} for the ``definition`` folder."""
    files = {
        "database.tmdl": render_database(),
        "model.tmdl": render_model(project),
        "expressions.tmdl": render_expressions(project),
    }
    if project.relationships:
        files["relationships.tmdl"] = render_relationships(project)
    for t in project.tables:
        files[f"tables/{table_file_name(t)}"] = render_table(project, t)
    return files
