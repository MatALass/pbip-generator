"""Power Query (M) expressions for each table source."""

from __future__ import annotations

import re

from .model import Column, DataType, Project, Table

PARAMETER_NAME = "DataFolder"
_PROMOTED = '#"Promoted Headers"'
_SIMPLE_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def m_string(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def m_id(name: str) -> str:
    """Identifier for a query or a step: Sales or #"Sales data"."""
    return name if _SIMPLE_ID.match(name) else "#" + m_string(name)


def m_field(name: str) -> str:
    """Field access: [Amount] or [#"Order date"]."""
    return f"[{m_id(name)}]"


def m_type(col: Column) -> str:
    return {
        DataType.STRING: "type text",
        DataType.INT64: "Int64.Type",
        DataType.DOUBLE: "type number",
        DataType.BOOLEAN: "type logical",
        DataType.DATETIME: "type date" if col.is_date_only else "type datetime",
    }[col.data_type]


def _type_step(table: Table, previous: str) -> str:
    pairs = ", ".join(f"{{{m_string(c.source_column)}, {m_type(c)}}}" for c in table.columns)
    culture = m_string(table.source.culture)
    return f"Table.TransformColumnTypes({previous}, {{{pairs}}}, {culture})"


def table_expression(project: Project, table: Table) -> str:
    src = table.source
    if src.kind == "date":
        # Generated calendar. A CSV/Excel table marked as date table keeps its own source.
        return date_table_expression(project)
    path = f"{PARAMETER_NAME} & {m_string(src.file_name)}"
    if src.kind == "csv":
        lines = [
            "let",
            f"    Source = Csv.Document(File.Contents({path}), [Delimiter={m_string(src.delimiter)}, "
            f"Encoding={src.encoding}, QuoteStyle=QuoteStyle.Csv]),",
            '    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),',
            f'    #"Changed Type" = {_type_step(table, _PROMOTED)}',
            "in",
            '    #"Changed Type"',
        ]
    elif src.kind == "excel":
        sheet = m_string(src.sheet or "Sheet1")
        lines = [
            "let",
            f"    Source = Excel.Workbook(File.Contents({path}), null, true),",
            f'    Sheet = Source{{[Item={sheet}, Kind="Sheet"]}}[Data],',
            '    #"Promoted Headers" = Table.PromoteHeaders(Sheet, [PromoteAllScalars=true]),',
            f'    #"Changed Type" = {_type_step(table, _PROMOTED)}',
            "in",
            '    #"Changed Type"',
        ]
    else:
        raise ValueError(f"Unsupported source kind: {src.kind}")
    return "\n".join(lines)


def date_table_expression(project: Project) -> str:
    """Calendar spanning full years around every date column of the fact tables."""
    refs = []
    for fact in project.facts:
        for col in fact.columns:
            if col.data_type == DataType.DATETIME:
                refs.append(f"Date.From(List.Min({m_id(fact.name)}{m_field(col.name)}))")
                refs.append(f"Date.From(List.Max({m_id(fact.name)}{m_field(col.name)}))")
    if refs:
        bounds = ", ".join(refs)
        start = f"Date.StartOfYear(List.Min({{{bounds}}}))"
        end = f"Date.EndOfYear(List.Max({{{bounds}}}))"
    else:  # pragma: no cover - date table only exists when dates exist
        start, end = "#date(2020, 1, 1)", "Date.EndOfYear(DateTime.Date(DateTime.LocalNow()))"
    culture = m_string(project.culture)
    return "\n".join(
        [
            "let",
            f"    StartDate = {start},",
            f"    EndDate = {end},",
            "    Dates = List.Dates(StartDate, Duration.Days(EndDate - StartDate) + 1, #duration(1, 0, 0, 0)),",
            '    AsTable = Table.FromList(Dates, Splitter.SplitByNothing(), {"Date"}),',
            '    Typed = Table.TransformColumnTypes(AsTable, {{"Date", type date}}),',
            '    AddYear = Table.AddColumn(Typed, "Année", each Date.Year([Date]), Int64.Type),',
            '    AddQuarter = Table.AddColumn(AddYear, "Trimestre", '
            'each "T" & Text.From(Date.QuarterOfYear([Date])), type text),',
            '    AddMonthNum = Table.AddColumn(AddQuarter, "Mois numéro", each Date.Month([Date]), Int64.Type),',
            f'    AddMonth = Table.AddColumn(AddMonthNum, "Mois", '
            f"each Text.Proper(Date.MonthName([Date], {culture})), type text),",
            '    AddYearMonth = Table.AddColumn(AddMonth, "Année-Mois", '
            'each Text.From(Date.Year([Date])) & "-" & Text.PadStart(Text.From(Date.Month([Date])), 2, "0"), '
            "type text),",
            '    AddDayNum = Table.AddColumn(AddYearMonth, "Jour semaine numéro", '
            "each Date.DayOfWeek([Date], Day.Monday) + 1, Int64.Type),",
            f'    AddDay = Table.AddColumn(AddDayNum, "Jour semaine", '
            f"each Text.Proper(Date.DayOfWeekName([Date], {culture})), type text)",
            "in",
            "    AddDay",
        ]
    )


def parameter_expression(project: Project) -> str:
    return f'{m_string(project.data_folder)} meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'
