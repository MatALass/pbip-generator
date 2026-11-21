"""MCP server: lets Claude (Desktop, Code) profile data, write a report spec and generate the PBIP.

The model decides *what* the report shows (the spec); this code does everything else. Run with
``pbip-generator-mcp`` (stdio). Each tool is a plain function, so it can be tested without MCP.

Typical loop: ``profile_data`` -> write a spec -> ``validate_spec`` until it returns no issue ->
``generate_report``.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from .builder import write_project
from .checks import check_pages
from .errors import AccessError, PbipGeneratorError
from .inference import infer_project
from .labels import labels
from .model import Project, TableRole
from .spec import TEMPLATE_SLOTS, SpecError, build_project_from_spec, parse_spec, spec_json_schema

# Tool parameter types, at module level: the MCP SDK resolves annotations against this module.
DataDir = Annotated[str, Field(description="Absolute path of the folder holding the CSV/Excel files")]
Spec = Annotated[dict[str, Any], Field(description="Report spec, as described by get_spec_schema")]

INSTRUCTIONS = """\
Build Power BI reports (PBIP projects) from a folder of CSV/Excel files.

1. Call profile_data on the folder: it returns the tables, columns, relationships and the measures
   created automatically. Use only these names.
2. Write a report spec for the reader's question (see get_spec_schema). Rules of thumb:
   - one question per page, written in 'purpose'; 2 to 4 pages;
   - KPIs at the top are measures; add the measures you need in 'measures' (DAX, DIVIDE for ratios,
     a format such as '#,##0 €' or '0.0 %', a description a business reader understands);
   - charts take a readable column as category (never an ID) and measures as values;
   - donut: 6 categories at most; column chart: 12; bar chart: 20; otherwise a table;
   - a measure across two dimensions (agent x map, product x month) is a pivotTable (matrix):
     'rows' (1 to 3 columns), 'columns' (one column, 12 values at most), 'values' (measures);
   - set 'language' to the reader's language (fr or en): it names the calendar and the automatic
     measures, so profile the data again after changing it;
   - pick a theme for the audience (theme.preset light or dark, optional accent color);
   - color the measure a reader must notice with 'highlights' (thresholds -> good/neutral/bad...),
     turn 'totals' off on tables whose columns are ratios, and use 'single_select' for a slicer
     the page needs exactly one value of (one team, one client);
   - hide the rows of a table that rest on too few data points with a visual filter on a count
     measure ('filters': [{field: '[Nb ...]', operator: '>=', value: 5}]).
3. Call validate_spec until it returns no issue: each issue says what is available instead.
4. Call generate_report. The user opens the .pbip in Power BI Desktop and clicks Refresh.
Never write TMDL or PBIR yourself.
"""


ALLOWED_ROOTS_VAR = "PBIP_ALLOWED_ROOTS"


def allowed_roots() -> list[Path]:
    """Folders the server may read from and write to, from PBIP_ALLOWED_ROOTS (os.pathsep-separated)."""
    raw = os.environ.get(ALLOWED_ROOTS_VAR, "")
    return [Path(p).expanduser().resolve() for p in raw.split(os.pathsep) if p.strip()]


def _allowed(path: str, purpose: str) -> Path:
    """The resolved path, if it lies inside an allowed root.

    The model chooses every path it passes to the tools: without this check it could read any file
    of the machine (profile_data) or write anywhere (generate_report). Symlinks and '..' are resolved
    before the check, and nothing is allowed until PBIP_ALLOWED_ROOTS is set.
    """
    roots = allowed_roots()
    if not roots:
        raise AccessError(
            f"{ALLOWED_ROOTS_VAR} is not set: no folder is allowed. Set it in the MCP server configuration "
            f"to the folders holding your data and reports (separated by '{os.pathsep}')."
        )
    resolved = Path(path).expanduser().resolve()
    if not any(resolved.is_relative_to(root) for root in roots):
        raise AccessError(
            f"The {purpose} {resolved} is outside the allowed folders: {', '.join(str(r) for r in roots)}"
        )
    return resolved


def _data_dir(path: str) -> Path:
    folder = _allowed(path, "data folder")
    if not folder.is_dir():
        raise FileNotFoundError(f"Data folder not found: {folder}")
    return folder


def profile(project: Project) -> dict[str, Any]:
    """What a spec can refer to: tables, visible columns, relationships, measures."""
    tables = []
    for t in project.tables:
        tables.append(
            {
                "name": t.name,
                "role": t.role.value,
                "rows": t.row_count,
                **({"sampled": True} if t.sampled else {}),
                "columns": [
                    {
                        "name": c.name,
                        "type": c.data_type.value,
                        "distinct": c.distinct_count,
                        **({"format": c.format_string} if c.format_string else {}),
                        **({"hidden": True} if c.is_hidden else {}),
                    }
                    for c in t.columns
                ],
                "measures": [
                    {"name": m.name, "expression": m.expression, "format": m.format_string, "folder": m.display_folder}
                    for m in t.measures
                ],
            }
        )
    return {
        "tables": tables,
        "relationships": [
            {
                "from": f"{r.from_table}[{r.from_column}]",
                "to": f"{r.to_table}[{r.to_column}]",
                **({} if r.is_active else {"active": False}),
            }
            for r in project.relationships
        ],
        "notes": [
            "Reference columns as 'Table[Column]' and measures as '[Measure]'.",
            "Hidden columns are technical keys: do not show them.",
            "distinct is the number of values of the column (chart readability).",
            "sampled tables were read on their first rows only: their distinct counts are lower bounds.",
        ]
        + (
            [_calendar_note(project)]
            if any(t.role == TableRole.DATE and t.source.kind == "date" for t in project.tables)
            else []
        ),
    }


def _calendar_note(project: Project) -> str:
    w = labels(project.language)
    cal = w["calendar"]
    return (
        f"{cal} is generated: use {cal}[{w['year']}] for slicers, {cal}[{w['year_month']}] for monthly trends, "
        f"{cal}[{w['month']}] for seasonality."
    )


def profile_data(data_dir: str) -> dict[str, Any]:
    return profile(infer_project(_data_dir(data_dir), "Profile"))


def get_spec_schema() -> dict[str, Any]:
    return {"schema": spec_json_schema(), "template_slots": TEMPLATE_SLOTS, "guide": INSTRUCTIONS}


def validate_spec(data_dir: str, spec: dict[str, Any]) -> dict[str, Any]:
    try:
        project = build_project_from_spec(_data_dir(data_dir), parse_spec(spec))
    except SpecError as exc:
        return {"valid": False, "issues": exc.issues}
    layout = [str(i) for i in check_pages(project.pages)]
    return {
        "valid": not layout,
        "issues": layout,
        "pages": [{"name": p.display_name, "visuals": len(p.visuals)} for p in project.pages],
    }


def generate_report(
    data_dir: str,
    spec: dict[str, Any],
    output_dir: str,
    name: str | None = None,
    data_folder: str | None = None,
    copy_data: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    folder = _data_dir(data_dir)
    report = parse_spec(spec)
    output = _allowed(output_dir, "output folder")
    name = name or report.name or folder.resolve().name
    if copy_data and data_folder is None:
        # Power BI reads the copy shipped with the project, not the original folder.
        data_folder = str(output / name / "data")
    project = build_project_from_spec(folder, report, name, data_folder)
    root = write_project(project, output, overwrite=overwrite, copy_data=copy_data, strict=True)
    return {
        "project_folder": str(root),
        "pbip_file": str(root / f"{project.name}.pbip"),
        "data_folder_parameter": project.data_folder,
        "pages": [p.display_name for p in project.pages],
        "measures": [m.name for _, m in project.all_measures()],
        "dictionary_file": str(root / "DATA_DICTIONARY.md"),
        "next_steps": "Open the .pbip in Power BI Desktop, then click Refresh (the project opens without data).",
    }


def create_server():
    """Build the MCP server. Imported lazily: ``mcp`` is an optional dependency."""
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError

    server = MCPServer(name="pbip-generator", instructions=INSTRUCTIONS)
    expected = (PbipGeneratorError, OSError)  # input errors; anything else is a bug and keeps its traceback

    def safe(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except expected as exc:
                raise ToolError(str(exc)) from exc

        return wrapper

    @server.tool(
        name="profile_data",
        description="Profile a folder of CSV/Excel files: tables, columns, relationships, automatic measures.",
    )
    @safe
    def profile_data_tool(data_dir: DataDir) -> dict[str, Any]:
        return profile_data(data_dir)

    @server.tool(
        name="get_spec_schema",
        description="JSON schema of the report spec, the visuals each page template holds and how to write it.",
    )
    def get_spec_schema_tool() -> dict[str, Any]:
        return get_spec_schema()

    @server.tool(
        name="validate_spec",
        description="Check a report spec against the data without writing anything. Returns every issue.",
    )
    @safe
    def validate_spec_tool(data_dir: DataDir, spec: Spec) -> dict[str, Any]:
        return validate_spec(data_dir, spec)

    @server.tool(
        name="generate_report",
        description="Generate the Power BI project (PBIP) from a valid report spec, in <output_dir>/<name>.",
    )
    @safe
    def generate_report_tool(
        data_dir: DataDir,
        spec: Spec,
        output_dir: Annotated[str, Field(description="Absolute path of the folder the project is written in")],
        name: Annotated[str | None, Field(description="Project name, short, no spaces (default: spec name)")] = None,
        data_folder: Annotated[
            str | None,
            Field(description="Folder Power BI reads the files from (default: the copied data, or data_dir)"),
        ] = None,
        copy_data: Annotated[bool, Field(description="Copy the source files into <project>/data")] = True,
        overwrite: Annotated[bool, Field(description="Replace an existing project of the same name")] = False,
    ) -> dict[str, Any]:
        return generate_report(data_dir, spec, output_dir, name, data_folder, copy_data, overwrite)

    return server


def main() -> None:  # pragma: no cover - entry point
    create_server().run("stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
