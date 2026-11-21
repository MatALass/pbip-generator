# Changelog

All notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow
[Semantic Versioning](https://semver.org/).

## [0.2.0] - unreleased

### Added
- **Visual filters on measures** (spec `filters`: `field`, `operator`, `value`): written as an
  *Advanced* visual-level filter, the one Desktop creates from *Filters on this visual*. The fuel example
  uses it to leave out stations with fewer than 5 prices.
- **Public data example** (`examples/carburants`): official French fuel prices (Etalab), 70,771 prices of
  884 stations, a 3-page report spec, and `fetch_data.py` that rebuilds the data from a pinned commit.
- **Model diagram**: `DATA_DICTIONARY.md` starts with a Mermaid `erDiagram` of the model (drawn by GitHub).
- **Grain of fact tables**: a unique row ID, or the smallest unique set of dates and foreign keys,
  computed on the data and written in the dictionary (`Table.grain`).
- Unit prices and rates (`Prix unitaire`, `Prix au litre`, `price per kg`, `Taux`, `%`) are averaged:
  automatic measure `Moyenne <column>` / `Average <column>` and `summarizeBy: average`, instead of a sum.
- **Report spec** (`--spec report.yaml`): model overrides, measures and pages in one typed file (Pydantic),
  checked against the inferred model before anything is written, with suggestions for unknown names.
  `pbip-generator spec-schema` prints its JSON schema.
- **Page templates** (`kpis_2x2`, `kpis_1_2`, `kpis_2`, `kpis_table`, `table`): the spec names visuals,
  the code computes every position.
- **MCP server** (`pbip-generator-mcp`, extra `[mcp]`): `profile_data`, `get_spec_schema`, `validate_spec`
  and `generate_report` for Claude Desktop, Claude Code or any MCP client.
- **Built-in light and dark themes** (spec `theme`): page and card backgrounds, rounded borders, shadows,
  KPI, title, table and slicer styles.
- **Highlights**: color a measure by thresholds in a table or a card, through a hidden DAX color measure.
- Spec options `totals` (table total row) and `single_select` (slicer with exactly one value).
- Amounts carry their currency (from the report culture).
- Large files: inference reads the first 200,000 rows and counts the rest.
- Proof of output: a CI job on Windows loads every generated semantic model with TOM (the library
  Power BI uses), golden files freeze the generated files of the examples, trap datasets cover
  empty files, duplicate or blank headers, accents, cp1252, multi-sheet workbooks, keys around the
  90 % match threshold and a one-million-row file (time-limited).
- Duplicate column names (also differing only by case) and blank headers are reported: Power Query
  would not find the columns pandas renamed.
- Manual checklist for Power BI Desktop (`docs/manual-check.md`), MCP walkthrough (`docs/mcp-demo.md`).
- Release workflow publishing to PyPI with trusted publishing; package metadata.
- README: screenshot, *Why* and *Out of scope* sections, CI, coverage and license badges.
- **Matrix** visual (`pivotTable`): `rows` (1 to 3 levels), `columns` (one column, up to 12 values),
  `values`, with highlights and `totals` (subtotals).
- **French or English generated names** (`--language en`, `language` in a config or a spec): calendar
  table and columns, automatic measures, display folders, default pages and titles, color measures.
  The culture follows the language unless set.
- **Data dictionary**: `DATA_DICTIONARY.md` written with every project, and
  `pbip-generator dictionary` to write it alone.
- MCP server: `PBIP_ALLOWED_ROOTS` limits the folders the tools may read and write. Every path the
  model passes is resolved and checked; with the variable unset, every call is refused.

### Changed
- Projects are written atomically: built in a temporary folder next to the target, then swapped in.
  A failure while writing (disk full, locked file) leaves the previous project untouched.
- Clicking a table row filters the other visuals instead of highlighting them.
- Technical keys (IDs, codes) are hidden; text keys such as names stay visible.
- `N-1` is blank over more than a year instead of showing a misleading figure.
- Tables share their width between their columns; donuts show category and percentage.
- Input errors are explicit exceptions (`PbipGeneratorError` and subclasses). The CLI and the MCP server
  report them as messages; any other exception is a bug and keeps its traceback.

### Fixed
- The spec validation accepted no column created inside a DAX expression: `[@p]` after
  `ADDCOLUMNS(..., "@p", ...)` (also `SELECTCOLUMNS`, `SUMMARIZE`) is now known.
- `overwrite` no longer deletes the source data when the project is regenerated from its own
  `<project>/data` folder (`copy_data`): the data is copied into the new project before the old one goes.
- Project names are plain folder names: a name such as `../x`, `.` or `..` is refused, and the
  project folder must stay inside the output folder (it is deleted by `overwrite`).
- Readability limits apply to the generated calendar columns.
- An unquoted table name with accents in DAX (`Équipes[Équipe]`) is reported by the validation.

## [0.1.0] - 2026-11-18

### Added
- First release: PBIP project (TMDL model and PBIR report) from a folder of CSV or Excel files,
  with typed Power Query sources, star schema inference, calendar table, automatic measures,
  an overview and a detail page, YAML overrides, custom theme and layout checks.

[0.2.0]: https://github.com/MatALass/pbip-generator/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/MatALass/pbip-generator/commits/b6ae9af
