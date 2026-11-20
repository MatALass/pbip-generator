"""Data dictionary: the model's tables, columns, relationships and measures as Markdown.

Written next to every project (``DATA_DICTIONARY.md``) and available alone through
``pbip-generator dictionary``: documentation that stays in sync because it is generated from the
same model as the TMDL.
"""

from __future__ import annotations

from .labels import labels
from .model import Project, Table, TableRole


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ") if text not in (None, "") else ""


def _source(table: Table, w: dict[str, str]) -> str:
    if table.source.kind == "date":
        return w["generated_calendar"]
    if table.source.sheet:
        return f"`{table.source.file_name}` ({table.source.sheet})"
    return f"`{table.source.file_name}`"


def _role(table: Table, w: dict[str, str]) -> str:
    return w[f"role_{table.role.value}"]


def render_dictionary(project: Project) -> str:
    w = labels(project.language)
    yes, no = w["yes"], w["no"]
    measures = project.all_measures()
    lines = [
        f"# {w['dictionary'].format(project=project.name)}",
        "",
        w["generated"].format(
            tables=len(project.tables), measures=len(measures), relationships=len(project.relationships)
        ),
        "",
        f"## {w['tables']}",
        "",
        f"| {w['table']} | {w['role']} | {w['source']} | {w['rows']} | {w['columns']} | {w['measures']} |",
        "|---|---|---|---:|---:|---:|",
    ]
    # Facts first, then dimensions, then the calendar: the order a reader explores a star schema.
    order = {TableRole.FACT: 0, TableRole.DIMENSION: 1, TableRole.DATE: 2}
    tables = sorted(project.tables, key=lambda t: (order[t.role], t.name))
    for t in tables:
        rows = "" if t.source.kind == "date" else f"{t.row_count:,}".replace(",", " ")
        lines.append(
            f"| {_cell(t.name)} | {_role(t, w)} | {_source(t, w)} | {rows} | {len(t.columns)} | {len(t.measures)} |"
        )
    for t in tables:
        lines += [
            "",
            f"### {t.name}",
            "",
            f"| {w['column']} | {w['type']} | {w['format']} | {w['hidden']} |",
            "|---|---|---|---|",
        ]
        for c in t.columns:
            fmt = f"`{c.format_string}`" if c.format_string else ""
            lines.append(f"| {_cell(c.name)} | {c.data_type.value} | {fmt} | {yes if c.is_hidden else no} |")
    lines += ["", f"## {w['relationships']}", ""]
    if project.relationships:
        lines += [f"| {w['from']} | {w['to']} | {w['active']} |", "|---|---|---|"]
        for r in project.relationships:
            lines.append(
                f"| {_cell(r.from_table)}[{_cell(r.from_column)}] | {_cell(r.to_table)}[{_cell(r.to_column)}] "
                f"| {yes if r.is_active else no} |"
            )
    else:
        lines.append("-")
    lines += ["", f"## {w['measures']}", ""]
    if measures:
        lines += [
            f"| {w['measure']} | {w['table']} | {w['folder']} | {w['format']} | {w['description']} |",
            "|---|---|---|---|---|",
        ]
        for t, m in measures:
            fmt = f"`{m.format_string}`" if m.format_string else ""
            name = f"{_cell(m.name)} ({w['hidden'].lower()})" if m.is_hidden else _cell(m.name)
            lines.append(f"| {name} | {_cell(t.name)} | {_cell(m.display_folder)} | {fmt} | {_cell(m.description)} |")
        for t, m in measures:
            lines += [
                "",
                f"### {m.name}",
                "",
                f"{w['expression']} ({t.name}):",
                "",
                "```dax",
                m.expression.strip(),
                "```",
            ]
    else:
        lines.append("-")
    return "\n".join(lines) + "\n"
