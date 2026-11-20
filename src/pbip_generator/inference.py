"""Build a :class:`Project` from a folder of CSV / Excel files.

The heuristics are deliberately simple and predictable: anything they get
wrong can be corrected in the YAML config (see ``config.py``).
"""

from __future__ import annotations

import csv
import re
import unicodedata
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from .errors import DataError
from .model import (
    Column,
    DataType,
    Measure,
    Project,
    Relationship,
    Source,
    Table,
    TableRole,
)

if TYPE_CHECKING:
    from .config import ProjectConfig

SUPPORTED_SUFFIXES = {".csv", ".txt", ".xlsx", ".xlsm"}
# Rows read to infer types, keys and relationships. Bigger files are only counted: Power BI
# loads them in full at refresh, inference does not need every row.
SAMPLE_ROWS = 200_000
CHUNK_ROWS = 500_000
DATE_TABLE_NAME = "Calendrier"
_INT_RE = re.compile(r"^[+-]?\d+$")
_BOOL_VALUES = {"true", "false", "vrai", "faux", "yes", "no", "oui", "non"}
_YEAR_HINTS = ("annee", "year", "exercice")
_AMOUNT_HINTS = (
    "montant",
    "chiffre",
    "ca",
    "revenue",
    "sales",
    "amount",
    "vente",
    "prix",
    "price",
    "cout",
    "cost",
    "valeur",
    "value",
    "total",
    "marge",
    "margin",
)
# Words of a column name that make it an amount of money (whole words, after normalization).
_MONEY_WORDS = {
    "montant", "montants", "ca", "chiffre", "prix", "cout", "couts", "marge", "ht", "ttc", "tarif", "solde",
    "budget", "encaissement", "facture", "revenue", "revenues", "sales", "amount", "price", "cost", "costs", "margin",
}  # fmt: skip
_EURO_LANGUAGES = {"fr", "de", "es", "it", "nl", "pt", "fi", "el", "sk", "sl", "et", "lv", "lt"}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def normalize(name: str) -> str:
    """Lowercase, strip accents and non-alphanumerics: 'Client_ID' -> 'clientid'."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def is_key_like(name: str) -> bool:
    n = normalize(name)
    return (
        n == "id"
        or n.endswith("id")
        or n.startswith("id")
        or n.endswith("key")
        or n.startswith("code")
        or n.endswith("code")
        or (n.startswith("num") and len(n) <= 8)
    )


def table_name_from(stem: str) -> str:
    cleaned = re.sub(r"[_\-]+", " ", stem).strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else stem


def _singular(norm: str) -> str:
    for suffix in ("ies", "es", "s", "x"):
        if norm.endswith(suffix) and len(norm) > len(suffix) + 2:
            return norm[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return norm


# --------------------------------------------------------------------------- #
# Reading files
# --------------------------------------------------------------------------- #
def _sniff_csv(path: Path) -> tuple[str, str, int]:
    """Return (delimiter, python encoding, Power Query code page)."""
    raw = path.read_bytes()[:65536]
    try:
        sample = raw.decode("utf-8-sig")
        encoding, code_page = "utf-8-sig", 65001
    except UnicodeDecodeError:
        sample = raw.decode("cp1252", errors="replace")
        encoding, code_page = "cp1252", 1252
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
    return delimiter, encoding, code_page


def _read_csv(path: Path) -> tuple[pd.DataFrame, int, Source]:
    """(the first SAMPLE_ROWS rows, the file's row count, its source)."""
    delimiter, encoding, code_page = _sniff_csv(path)
    options = {"sep": delimiter, "encoding": encoding, "dtype": str, "keep_default_na": False}
    frame = pd.read_csv(path, nrows=SAMPLE_ROWS, **options)
    rows = len(frame)
    if rows == SAMPLE_ROWS:
        # Count the rest one column at a time, without holding the file in memory.
        chunks = pd.read_csv(path, usecols=[0], chunksize=CHUNK_ROWS, **options)
        rows = sum(len(chunk) for chunk in chunks)
    # A ';' separator usually means French-style numbers ("12,5") and dates.
    culture = "fr-FR" if delimiter == ";" else "en-US"
    source = Source(
        kind="csv",
        file_name=path.name,
        delimiter=delimiter,
        encoding=code_page,
        culture=culture,
    )
    return frame, rows, source


def _read_excel(path: Path) -> list[tuple[str, pd.DataFrame, int, Source]]:
    sheets = pd.read_excel(path, sheet_name=None, engine="openpyxl", nrows=SAMPLE_ROWS)
    out = []
    for sheet_name, frame in sheets.items():
        rows = len(frame)
        if rows == SAMPLE_ROWS:
            from openpyxl import load_workbook

            workbook = load_workbook(path, read_only=True)
            rows = max(workbook[str(sheet_name)].max_row - 1, rows)  # minus the header row
            workbook.close()
        frame = frame.dropna(axis=1, how="all").dropna(axis=0, how="all")
        if frame.empty:
            continue
        frame.columns = [str(c) for c in frame.columns]
        name = table_name_from(path.stem if len(sheets) == 1 else str(sheet_name))
        out.append((name, frame, rows, Source(kind="excel", file_name=path.name, sheet=str(sheet_name))))
    return out


def _raw_headers(path: Path, source: Source) -> list[str]:
    """Header row as written in the file: pandas renames duplicates ('A.1') and blanks ('Unnamed: 2'),
    Power Query does not, so the model would point at columns the refresh never finds."""
    if source.kind == "excel":
        first = pd.read_excel(path, sheet_name=source.sheet, header=None, nrows=1, engine="openpyxl")
        return ["" if pd.isna(v) else str(v) for v in first.iloc[0]] if len(first) else []
    _, encoding, _ = _sniff_csv(path)
    with path.open(encoding=encoding, newline="") as f:
        return next(csv.reader(f, delimiter=source.delimiter), [])


def _check_headers(path: Path, source: Source) -> None:
    where = path.name + (f" (sheet {source.sheet})" if source.sheet else "")
    headers = [h.strip() for h in _raw_headers(path, source)]
    while headers and not headers[-1]:  # trailing separators or empty Excel cells
        headers.pop()
    blank = [i + 1 for i, h in enumerate(headers) if not h]
    if blank:
        raise DataError(f"{where}: column {blank[0]} has no header, name it in the file")
    seen: dict[str, str] = {}
    for h in headers:
        # Power BI column names are case-insensitive: 'Montant' and 'montant' clash.
        if h.lower() in seen:
            raise DataError(f"{where}: columns '{seen[h.lower()]}' and '{h}' have the same name, rename one")
        seen[h.lower()] = h


def _read_source(path: Path) -> list[tuple[str, pd.DataFrame, int, Source]]:
    try:
        if path.suffix.lower() in (".csv", ".txt"):
            if path.stat().st_size == 0:
                raise DataError(f"{path.name} is empty")
            frame, rows, source = _read_csv(path)
            loaded = [(table_name_from(path.stem), frame, rows, source)]
        else:
            loaded = _read_excel(path)
        for _, _, _, source in loaded:
            _check_headers(path, source)
        return loaded
    except (ValueError, UnicodeError, zipfile.BadZipFile) as exc:  # pandas parser errors are ValueErrors
        if isinstance(exc, DataError):
            raise
        raise DataError(f"Cannot read {path.name}: {exc}") from exc


# --------------------------------------------------------------------------- #
# Type inference
# --------------------------------------------------------------------------- #
def _infer_text_series(values: pd.Series, culture: str) -> tuple[DataType, bool]:
    """Infer the type of a column read as text. Returns (type, is_date_only)."""
    s = values.astype(str).str.strip()
    s = s[s != ""]
    if s.empty:
        return DataType.STRING, False
    lowered = s.str.lower()
    if lowered.isin(_BOOL_VALUES).all():
        return DataType.BOOLEAN, False
    if s.str.match(_INT_RE).all():
        # Leading zeros ("00123") mean a code, not a number.
        if (s.str.lstrip("+-").str.len().gt(1) & s.str.lstrip("+-").str.startswith("0")).any():
            return DataType.STRING, False
        return DataType.INT64, False
    numeric_text = s.str.replace(" ", "", regex=False).str.replace(" ", "", regex=False)
    if culture == "fr-FR":
        numeric_text = numeric_text.str.replace(",", ".", regex=False)
    if pd.to_numeric(numeric_text, errors="coerce").notna().all():
        return DataType.DOUBLE, False
    parsed = _parse_dates(s, culture)
    if parsed is not None:
        date_only = bool((parsed.dt.normalize() == parsed).all())
        return DataType.DATETIME, date_only
    return DataType.STRING, False


def _parse_dates(s: pd.Series, culture: str) -> pd.Series | None:
    # Require something that looks like a date to avoid parsing free text.
    if not s.str.contains(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}", regex=True).all():
        return None
    attempts = [{"format": "ISO8601"}, {"dayfirst": culture == "fr-FR", "format": "mixed"}]
    for kwargs in attempts:
        try:
            parsed = pd.to_datetime(s, errors="raise", **kwargs)
        except (ValueError, TypeError):
            continue
        return parsed
    return None


def _infer_typed_series(values: pd.Series) -> tuple[DataType, bool]:
    s = values.dropna()
    if s.empty:
        return DataType.STRING, False
    if pd.api.types.is_bool_dtype(s):
        return DataType.BOOLEAN, False
    if pd.api.types.is_integer_dtype(s):
        return DataType.INT64, False
    if pd.api.types.is_float_dtype(s):
        if (s == s.round()).all() and s.abs().max() < 2**53:
            return DataType.INT64, False
        return DataType.DOUBLE, False
    if pd.api.types.is_datetime64_any_dtype(s):
        return DataType.DATETIME, bool((s.dt.normalize() == s).all())
    return _infer_text_series(s.astype(str), "en-US")


def _is_technical_key(col: Column) -> bool:
    """An ID or a code. A text key such as a team or agent name is what readers look for: it stays visible."""
    return col.data_type != DataType.STRING or is_key_like(col.name)


def _year_span(values: pd.Series, source: Source) -> tuple[int, int] | None:
    if pd.api.types.is_datetime64_any_dtype(values):
        dates = values
    else:
        dates = _parse_dates(values.astype(str).str.strip(), source.culture)
    if dates is None or dates.empty:
        return None
    return int(dates.min().year), int(dates.max().year)


def _build_columns(frame: pd.DataFrame, source: Source) -> list[Column]:
    columns: list[Column] = []
    for name in frame.columns:
        series = frame[name]
        if source.kind == "csv":
            data_type, date_only = _infer_text_series(series, source.culture)
            non_empty = series[series.astype(str).str.strip() != ""]
        else:
            data_type, date_only = _infer_typed_series(series)
            non_empty = series.dropna()
        distinct = int(non_empty.nunique())
        col = Column(
            name=str(name),
            data_type=data_type,
            is_date_only=date_only,
            distinct_count=distinct,
            is_unique=distinct == len(series) and len(series) > 0,
        )
        if data_type in (DataType.INT64, DataType.DOUBLE) and not is_key_like(col.name):
            col.summarize_by = "sum"
            col.format_string = "#,##0" if data_type == DataType.INT64 else "#,##0.00"
        if data_type == DataType.DATETIME:
            col.format_string = "dd/mm/yyyy" if date_only else "dd/mm/yyyy hh:nn"
            col.years = _year_span(non_empty, source)
        columns.append(col)
    return columns


def _values(frame: pd.DataFrame, column: str) -> set[str]:
    s = frame[column].dropna().astype(str).str.strip()
    s = s[s != ""]
    # "12.0" (Excel float) and "12" (CSV) must match.
    return {v[:-2] if v.endswith(".0") else v for v in s}


# --------------------------------------------------------------------------- #
# Relationships and roles
# --------------------------------------------------------------------------- #
def _full_column(path: Path, source: Source, column: str) -> pd.DataFrame:
    """One column of a whole file, read by chunks (the key of a sampled dimension)."""
    if source.kind == "excel":
        return pd.read_excel(path, sheet_name=source.sheet, usecols=[column], engine="openpyxl")
    delimiter, encoding, _ = _sniff_csv(path)
    options = {"sep": delimiter, "encoding": encoding, "dtype": str, "keep_default_na": False}
    chunks = pd.read_csv(path, usecols=[column], chunksize=CHUNK_ROWS, **options)
    return pd.concat(chunks, ignore_index=True)


def _detect_relationships(
    tables: list[Table], frames: dict[str, pd.DataFrame], data_dir: Path | None = None
) -> list[Relationship]:
    """Many-to-one links. The many side can be a sample (its values are a subset); the one side of a
    sampled table is read in full for the candidate column, or its keys would look missing."""
    full: dict[tuple[str, str], set[str]] = {}

    def one_values(table: Table, column: str) -> set[str]:
        if not table.sampled or data_dir is None:
            return _values(frames[table.name], column)
        if (table.name, column) not in full:
            frame = _full_column(data_dir / table.source.file_name, table.source, column)
            full[(table.name, column)] = _values(frame, column)
        return full[(table.name, column)]

    candidates: list[tuple[float, Relationship]] = []
    for one in tables:
        for one_col in one.columns:
            if not one_col.is_unique or one_col.data_type in (DataType.DOUBLE, DataType.BOOLEAN):
                continue
            if not is_key_like(one_col.name) and one_col.data_type != DataType.STRING:
                continue
            one_norm = normalize(one_col.name)
            accepted = {one_norm}
            if one_norm in ("id", "code", "key"):
                accepted.add(_singular(normalize(one.name)) + one_norm)
            for many in tables:
                if many is one:
                    continue
                for many_col in many.columns:
                    if normalize(many_col.name) not in accepted:
                        continue
                    if many_col.data_type != one_col.data_type:
                        continue
                    many_vals = _values(frames[many.name], many_col.name)
                    if not many_vals:
                        continue
                    one_vals = one_values(one, one_col.name)
                    coverage = len(many_vals & one_vals) / len(many_vals)
                    if coverage < 0.9:
                        continue
                    if many_col.is_unique and len(many_vals) == len(one_vals):
                        continue  # 1:1, ambiguous direction: leave to the user
                    candidates.append((coverage, Relationship(many.name, many_col.name, one.name, one_col.name)))
    return _deduplicate_paths([r for _, r in sorted(candidates, key=lambda c: -c[0])])


def _deduplicate_paths(rels: list[Relationship]) -> list[Relationship]:
    """Keep the model a tree: an edge that would close a cycle becomes inactive."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    seen_pairs: set[tuple[str, str]] = set()
    for rel in rels:
        pair = (rel.from_table, rel.to_table)
        a, b = find(rel.from_table), find(rel.to_table)
        if pair in seen_pairs or a == b:
            rel.is_active = False
        else:
            parent[a] = b
        seen_pairs.add(pair)
    return rels


def _assign_roles(tables: list[Table], rels: list[Relationship]) -> None:
    many_side = {r.from_table for r in rels}
    one_side = {r.to_table for r in rels}
    for t in tables:
        if t.name in many_side and t.name not in one_side:
            t.role = TableRole.FACT
        else:
            t.role = TableRole.DIMENSION
    if not any(t.role == TableRole.FACT for t in tables):
        # No relationship: the table with the most numeric measures is the fact.
        def score(t: Table) -> tuple[int, int]:
            return (sum(c.summarize_by == "sum" for c in t.columns), t.row_count)

        max(tables, key=score).role = TableRole.FACT


# --------------------------------------------------------------------------- #
# Date table and measures
# --------------------------------------------------------------------------- #
def _add_date_table(project: Project) -> None:
    date_cols = [(t, c) for t in project.facts for c in t.columns if c.data_type == DataType.DATETIME]
    if not date_cols or project.has_table(DATE_TABLE_NAME) or project.date_table is not None:
        return
    cal = Table(
        name=DATE_TABLE_NAME,
        role=TableRole.DATE,
        source=Source(kind="date"),
        columns=[
            Column(
                "Date", DataType.DATETIME, is_date_only=True, is_key=True, format_string="dd/mm/yyyy", is_unique=True
            ),
            Column("Année", DataType.INT64, format_string="0"),
            Column("Trimestre", DataType.STRING),
            Column("Mois numéro", DataType.INT64, is_hidden=True, format_string="0"),
            Column("Mois", DataType.STRING, sort_by_column="Mois numéro"),
            Column("Année-Mois", DataType.STRING),
            Column("Jour semaine numéro", DataType.INT64, is_hidden=True, format_string="0"),
            Column("Jour semaine", DataType.STRING, sort_by_column="Jour semaine numéro"),
        ],
    )
    spans = [c.years for _, c in date_cols if c.years is not None]
    if spans:
        # The calendar spans the full years of the data (see mquery.date_table_query): its number
        # of values per column is known, so readability limits apply to it too.
        n_years = max(y for _, y in spans) - min(y for y, _ in spans) + 1
        counts = {"Date": 365 * n_years, "Année": n_years, "Trimestre": 4, "Mois numéro": 12, "Mois": 12,
                  "Année-Mois": 12 * n_years, "Jour semaine numéro": 7, "Jour semaine": 7}  # fmt: skip
        for col in cal.columns:
            col.distinct_count = counts[col.name]
    project.tables.append(cal)
    active_done: set[str] = set()
    for table, col in date_cols:
        project.relationships.append(
            Relationship(
                from_table=table.name,
                from_column=col.name,
                to_table=DATE_TABLE_NAME,
                to_column="Date",
                is_active=table.name not in active_done,
                date_part_only=not col.is_date_only,
            )
        )
        active_done.add(table.name)
        col.is_hidden = True


def _is_year_like(col: Column) -> bool:
    return any(h in normalize(col.name) for h in _YEAR_HINTS)


def is_money_like(name: str) -> bool:
    words = (normalize(w) for w in re.split(r"[\s_\-/.()]+", name))
    return any(w in _MONEY_WORDS for w in words)


def currency_format(culture: str, decimals: bool) -> str:
    """Format string of an amount: '#,##0 €' in euro countries, '$#,##0' in the US, else no symbol."""
    number = "#,##0.00" if decimals else "#,##0"
    language = culture.split("-")[0].lower()
    if language in _EURO_LANGUAGES:
        return f"{number} €"
    if culture == "en-US":
        return f"${number}"
    return number


def _apply_currency(project: Project) -> None:
    """Show amounts of money with their currency, columns with cents, measures without."""
    for table in project.tables:
        for col in table.columns:
            if col.summarize_by == "sum" and is_money_like(col.name):
                col.format_string = currency_format(project.culture, col.data_type == DataType.DOUBLE)


def _add_measures(project: Project) -> None:
    cal = project.date_table
    for fact in project.facts:
        ref = quote_dax_table(fact.name)
        measures: list[Measure] = []
        numeric = [c for c in fact.columns if c.summarize_by == "sum" and not _is_year_like(c)]
        # The first measure becomes the "primary" one used by charts: prefer amounts.
        numeric.sort(
            key=lambda c: (not any(h in normalize(c.name) for h in _AMOUNT_HINTS), c.data_type != DataType.DOUBLE)
        )
        for col in numeric:
            money = is_money_like(col.name)
            measures.append(
                Measure(
                    name=f"Total {col.name}",
                    expression=f"SUM({ref}[{col.name}])",
                    format_string=currency_format(project.culture, False) if money else col.format_string,
                    display_folder="Base",
                )
            )
        measures.append(
            Measure(
                name=f"Nb {fact.name}",
                expression=f"COUNTROWS({ref})",
                format_string="#,##0",
                display_folder="Base",
            )
        )
        if cal is not None:
            primary = measures[0]
            key = next((c.name for c in cal.columns if c.is_key), "Date")
            date_ref = f"{quote_dax_table(cal.name)}[{key}]"
            base = f"[{primary.name}]"
            # Over more than a year (no year selected), "last year" has no meaning: blank instead of
            # a misleading figure. The variation inherits the blank.
            last_year = (
                f"IF(\n    DATEDIFF(MIN({date_ref}), MAX({date_ref}), DAY) < 366,\n"
                f"    CALCULATE({base}, SAMEPERIODLASTYEAR({date_ref}))\n)"
            )
            measures += [
                Measure(
                    f"{primary.name} N-1",
                    last_year,
                    primary.format_string,
                    "Temps",
                ),
                Measure(
                    f"{primary.name} Var % N-1",
                    f"VAR _n = {base}\nVAR _n1 = [{primary.name} N-1]\nRETURN DIVIDE(_n - _n1, _n1)",
                    "0.0 %;-0.0 %;0.0 %",
                    "Temps",
                ),
                Measure(
                    f"{primary.name} Cumul annuel", f"TOTALYTD({base}, {date_ref})", primary.format_string, "Temps"
                ),
            ]
        existing = {m.name for m in fact.measures}
        fact.measures.extend(m for m in measures if m.name not in existing)


def quote_dax_table(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) else "'" + name.replace("'", "''") + "'"


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def infer_project(
    data_dir: Path,
    name: str,
    data_folder: str | None = None,
    config: ProjectConfig | None = None,
) -> Project:
    """Read every source in ``data_dir`` and build the full project.

    Order matters: base inference, then user overrides (roles, types,
    relationships), then the derived parts (date table, measures).
    """
    from .config import ProjectConfig  # local import to avoid a cycle

    config = config or ProjectConfig()
    data_dir = Path(data_dir)
    files = sorted(
        p
        for p in data_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES and not p.name.startswith("~$")
    )
    if not files:
        raise FileNotFoundError(f"No CSV/Excel file found in {data_dir}")

    tables: list[Table] = []
    frames: dict[str, pd.DataFrame] = {}
    loaded = [source for path in files for source in _read_source(path)]

    for tname, frame, rows, source in loaded:
        if tname in frames:
            raise DataError(f"Two sources produce the same table name '{tname}'")
        frames[tname] = frame
        columns = _build_columns(frame, source)
        table = Table(name=tname, columns=columns, source=source, row_count=rows, sampled=rows > len(frame))
        tables.append(table)

    rels = _detect_relationships(tables, frames, data_dir) if config.auto_relationships else []
    _assign_roles(tables, rels)

    data_folder = data_folder or config.data_folder or str(data_dir.resolve())
    if not data_folder.endswith(("\\", "/")):
        windows = "\\" in data_folder or re.match(r"^[A-Za-z]:", data_folder)
        data_folder += "\\" if windows else "/"

    project = Project(
        name=name,
        tables=tables,
        relationships=rels,
        data_folder=data_folder,
        culture=config.culture,
        source_dir=data_dir,
    )
    config.apply_structure(project)
    for rel in project.relationships:
        many = project.table(rel.from_table).column(rel.from_column)
        many.is_hidden = True
        many.summarize_by = "none"
        one = project.table(rel.to_table).column(rel.to_column)
        one.summarize_by = "none"
        if project.table(rel.to_table).role != TableRole.DATE and _is_technical_key(one):
            one.is_hidden = True  # an ID: readers use the dimension's labels instead
    for fact in project.facts:
        for col in fact.columns:
            if col.is_unique and is_key_like(col.name):
                col.is_hidden = True  # a row ID of the fact table
    _apply_currency(project)
    if config.date_table:
        _add_date_table(project)
    if config.auto_measures:
        _add_measures(project)
    config.apply_theme(project)
    config.apply_measures(project)
    return project
