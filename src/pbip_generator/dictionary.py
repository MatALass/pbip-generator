"""Data dictionary: the model's tables, columns, relationships and measures as Markdown.

Written next to every project (``DATA_DICTIONARY.md``) and available alone through
``pbip-generator dictionary``: documentation that stays in sync because it is generated from the
same model as the TMDL.
"""

from __future__ import annotations

import re
import unicodedata

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


def _entity(index: int) -> str:
    return f"T{index}"


def _attribute(name: str) -> str:
    """Mermaid attribute names are plain ASCII words: 'Date relevé' -> 'Date_releve'."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    token = re.sub(r"[^A-Za-z0-9_]+", "_", ascii_name).strip("_")
    return token or "col"


def render_diagram(project: Project) -> str:
    """The model as a Mermaid ``erDiagram``: GitHub and most Markdown viewers draw it as an image.

    Every table with its key columns (PK on the one side, FK on the many side), every relationship
    (dotted when inactive). The original name is kept as a comment when it had to be simplified.
    """
    order = {TableRole.FACT: 0, TableRole.DIMENSION: 1, TableRole.DATE: 2}
    tables = sorted(project.tables, key=lambda t: (order[t.role], t.name))
    ids = {t.name: _entity(i) for i, t in enumerate(tables)}
    pk = {(r.to_table, r.to_column) for r in project.relationships}
    fk = {(r.from_table, r.from_column) for r in project.relationships}
    w = labels(project.language)
    lines = ["```mermaid", "erDiagram"]
    for t in tables:
        label = f"{t.name} ({w[f'role_{t.role.value}']})"
        lines.append(f'    {ids[t.name]}["{label}"] {{')
        for c in t.columns:
            marks = [m for m, keys in (("PK", pk), ("FK", fk)) if (t.name, c.name) in keys]
            row_id = t.role == TableRole.FACT and t.grain == [c.name]
            if (c.is_key or row_id) and "PK" not in marks:
                marks.insert(0, "PK")
            if not marks:
                continue
            comment = f' "{c.name}"' if _attribute(c.name) != c.name else ""
            lines.append(f"        {c.data_type.value} {_attribute(c.name)} {','.join(marks)}{comment}")
        lines.append("    }")
    for r in project.relationships:
        link = "--" if r.is_active else ".."
        lines.append(f'    {ids[r.from_table]} }}o{link}|| {ids[r.to_table]} : "{r.from_column}"')
    lines.append("```")
    return "\n".join(lines)


def render_grain(project: Project) -> list[str]:
    w = labels(project.language)
    out = []
    for t in project.facts:
        if t.grain is None:
            continue
        if t.grain:
            text = w["grain_of"].format(columns=" + ".join(f"`{c}`" for c in t.grain))
        else:
            text = w["grain_unknown"]
        if t.sampled:
            from .inference import SAMPLE_ROWS

            text += w["grain_sampled"].format(rows=f"{SAMPLE_ROWS:,}".replace(",", " "))
        out.append(f"- **{t.name}** : {text}" if project.language == "fr" else f"- **{t.name}**: {text}")
    return out


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
    lines += ["", f"## {w['diagram']}", "", render_diagram(project)]
    grain = render_grain(project)
    if grain:
        lines += ["", f"## {w['grain']}", "", *grain]
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
