# pbip-generator

Generate a complete, ready-to-open **Power BI project** from a folder of CSV or Excel files.

It writes a [Power BI Project (PBIP)](https://learn.microsoft.com/power-bi/developer/projects/projects-overview):
a semantic model in **TMDL** and a report in **PBIR**, both plain text. You open the `.pbip` in
Power BI Desktop, click *Refresh*, and get a working star schema with measures and two report pages.

```
data/                         output/Ventes/
├── clients.csv     ──►       ├── Ventes.pbip
├── produits.csv              ├── Ventes.SemanticModel/definition/   (TMDL)
└── ventes.csv                └── Ventes.Report/definition/          (PBIR)
```

## What it builds

| Layer | Generated automatically |
|---|---|
| Power Query | One query per CSV file / Excel sheet, typed columns, a `DataFolder` parameter |
| Model | Fact/dimension detection, many-to-one relationships, key columns hidden, a cycle-free graph |
| Calendar | `Calendrier` table spanning the data's full years, month/weekday sort orders, marked as date table |
| Measures | `Total <column>` per numeric column, `Nb <table>`, and N-1, variation % and year-to-date for the main measure |
| Report | *Vue d'ensemble* page (slicers, KPI cards, line, column, bar and donut charts) and a *Détail* page (table) |

Everything inferred can be corrected or extended with a YAML file (roles, types, relationships,
hidden columns, custom DAX measures). Output is deterministic: same input, same files, clean git diffs.

## Install

```bash
pip install git+https://github.com/<you>/pbip-generator
# or, from a clone
pip install -e ".[dev]"
```

Requires Python 3.10+.

## Usage

```bash
# 1. Generate
pbip-generator build path/to/data -o output --name Ventes

# 2. Optional: dump what was inferred, edit it, regenerate
pbip-generator init-config path/to/data -o config.yaml
pbip-generator build path/to/data -c config.yaml -o output --overwrite
```

Useful options:

| Option | Purpose |
|---|---|
| `--data-folder "C:\Users\me\data\"` | Folder Power BI reads from, on the machine that opens the project. Defaults to the absolute path of the input folder. Can also be changed later in Power BI (*Transform data > Edit parameters*). |
| `--copy-data` | Copy the source files into `<project>/data`, to ship the project as a single folder |
| `-c config.yaml` | Overrides (see [`examples/ventes/config.yaml`](examples/ventes/config.yaml) and the docstring of `config.py`) |

### Config example

```yaml
theme: theme.json             # a Power BI theme file, path relative to the YAML
tables:
  Calendrier:
    role: date                # your own date table instead of the generated one
    key: Date                 # its unique date column (marked as date table)
  Ventes:
    role: fact
    types: {CodePostal: string}
    hide: [Commentaire]
    measures:
      - name: Panier moyen
        expression: DIVIDE([Total Montant], [Nb Ventes])
        format: '#,##0.00 €'
relationships:
  add:
    - {from: Ventes[MagasinID], to: Magasins[ID]}
  remove:
    - {from: Ventes[ProduitID], to: Produits[ProduitID]}
```

### Theme

`theme:` takes the same JSON you would import in Desktop (*View > Themes > Browse for themes*).
It is written to `<Name>.Report/StaticResources/RegisteredResources/` and registered in
`report.json`, so the report opens already styled.

### Report spec: describe the pages, not their pixels

A report spec (YAML or JSON) holds the model overrides of the config *and* the pages. Each page
picks a template and lists its slicers, KPIs and visuals by name; the code computes every position.

```bash
pbip-generator build examples/ventes/data --spec examples/ventes/report.yaml -o output --strict
pbip-generator spec-schema -o report-spec.schema.json   # JSON schema, e.g. for a language model
```

```yaml
business_question: Où se fait le chiffre d'affaires et comment évolue-t-il ?
audience: direction                 # daf | direction | commercial | operationnel
measures:
  - {table: Ventes, name: Panier moyen, expression: 'DIVIDE([Total Montant], [Nb Ventes])',
     format: '#,##0.00 €', description: Montant moyen d'une vente}
pages:
  - name: Synthèse
    purpose: Voir en 10 secondes le CA, sa tendance et où il se fait
    template: kpis_1_2               # kpis_2x2 | kpis_1_2 | kpis_2 | kpis_table | table
    slicers: ['Calendrier[Année]', 'Clients[Région]']
    kpis: ['[Total Montant]', '[Panier moyen]']
    visuals:
      - {type: lineChart, title: CA par mois, category: 'Calendrier[Année-Mois]', values: ['[Total Montant]']}
      - ...
```

Every page gets a title, up to 3 slicers and up to 4 KPI cards on top, then the template's slots
(`kpis_2x2`: 4, `kpis_1_2`: 1 wide + 2, `kpis_2`: 2, `kpis_table` and `table`: 1 full width).
Before anything is written, the spec is checked against the inferred model: unknown keys, unknown
tables, columns and measures (with close-name suggestions), DAX references, a column where a
measure is expected, hidden key columns, charts with too many categories, and the number of visuals
of each template. All issues are reported at once, so the spec can be fixed in one pass.

### MCP server: let Claude write the spec

`pbip-generator-mcp` is a local [MCP](https://modelcontextprotocol.io) server (stdio) for Claude
Desktop, Claude Code or any MCP client. Claude decides what the report shows; this code writes
every file. Tools:

| Tool | Does |
|---|---|
| `profile_data` | Tables, columns (type, number of values, hidden keys), relationships and automatic measures of a data folder |
| `get_spec_schema` | JSON schema of the report spec, the template slots and the writing guide |
| `validate_spec` | Every issue of a spec against the data, without writing anything |
| `generate_report` | Writes `<output_dir>/<name>/<name>.pbip`, data copied next to it by default |

```bash
pip install -e ".[mcp]"
```

Claude Code, from the folder you work in (use the full path of the executable of your environment):

```bash
claude mcp add pbip-generator -- "C:\path\to\pbip-generator\.venv\Scripts\pbip-generator-mcp.exe"
```

Claude Desktop: *Settings > Developer > Edit config*, then in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pbip-generator": {
      "command": "C:\\path\\to\\pbip-generator\\.venv\\Scripts\\pbip-generator-mcp.exe"
    }
  }
}
```

Restart Claude Desktop, then ask for a report: *"Here is my billing data in C:\data\facturation,
build a monthly invoicing report for a CFO in C:\pbip"*.

### Writing the pages yourself

Automatic pages are a starting point. For a real report, build the `Project` in Python and set
`project.pages` with your own `Visual` objects (position, roles, title, sort). A `textbox`
visual takes `text` and `text_size` for page titles:

```python
Visual("textbox", {}, 16, 16, 600, 56, text="Stock & Reallocation", text_size=24)
```

### Layout checks

Before writing, every page is checked: visuals that overlap, go past the page edge, have no field,
or are smaller than the size their data needs (a dropdown slicer under 56 px only draws its header,
for example). Issues are printed as warnings; `--strict` (or `write_project(..., strict=True)`)
turns them into an error. `check_project(project)` returns the list, to assert on it in a test:

```python
from pbip_generator import check_project
assert check_project(build_project()) == []
```

Slicers carry their label in the slicer header and hide the container title, so a theme that
switches titles on for every visual cannot push the dropdown out of the slicer. Titled cards hide
their category label, which would repeat the title.

## Opening the project in Power BI Desktop

1. In *File > Options and settings > Options > Preview features*, enable **Power BI Project (.pbip) save option**,
   **Store semantic model using TMDL format** and **Store reports using enhanced metadata format (PBIR)**
   (recent Desktop versions may have some of them enabled by default).
2. Open `<Name>.pbip`. The model loads without data: click **Refresh**.
3. To get a single file, *File > Save as > .pbix*.

## How inference works

- **Types**: CSV columns are read as text and typed explicitly (int, decimal, date, datetime, boolean, text).
  Codes with leading zeros stay text. A `;` separator switches to French parsing (`1 234,50`, `31/12/2024`).
- **Relationships**: a column is linked to a unique column with the same normalized name in another table
  (`Client_ID` = `ClientID`), or to `ID` in a table named after it (`ClientID` → `Clients[ID]`),
  when at least 90 % of its values exist on the one side. Any edge that would create a second path
  between two tables becomes inactive.
- **Roles**: a table only on the many side is a fact; with no relationship, the table with the most
  numeric columns is the fact.
- **Main measure**: amounts (`montant`, `CA`, `sales`, `prix`...) first, then decimals, then integers.

## Development

```bash
pip install -e ".[dev]"
git clone --depth=1 --filter=blob:none --sparse https://github.com/microsoft/json-schemas.git .schemas-src
git -C .schemas-src sparse-checkout set fabric
PBIP_SCHEMAS_DIR=.schemas-src/fabric pytest
ruff check src tests && ruff format --check src tests
```

Every generated JSON file is validated against Microsoft's official
[Fabric JSON schemas](https://github.com/microsoft/json-schemas/tree/main/fabric) in the test suite.

```
src/pbip_generator/
├── inference.py   # read files, infer types, relationships, roles, calendar, measures
├── config.py      # YAML overrides
├── mquery.py      # Power Query (M) expressions
├── tmdl.py        # semantic model writer (TMDL)
├── layout.py      # automatic report layout
├── checks.py      # layout checks (overlaps, sizes, page bounds)
├── pbir.py        # report writer (PBIR) and PBIP wrapper files
├── builder.py     # assemble and write the project folder
└── cli.py
```

## Limitations

- Import mode only, CSV/Excel sources only (no database connectors yet).
- 1:1 relationships are not created automatically (direction is ambiguous): add them in the config.
- PBIP, TMDL and PBIR are evolving formats; files target the schema versions listed in `pbir.py`.

## License

MIT
