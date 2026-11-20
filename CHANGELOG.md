# Changelog

All notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow
[Semantic Versioning](https://semver.org/).

## [0.2.0] - unreleased

### Added
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
- `CHANGELOG.md`, CI and license badges.

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
