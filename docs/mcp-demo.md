# From a prompt to a report: Claude with the MCP server

This is a real run, shortened: Claude Desktop with `pbip-generator-mcp` registered, on the sample
data in `examples/ventes/data`. Tool results are trimmed to what matters.

## The prompt

> The data is in `C:\pbip-generator\examples\ventes\data`. Build a sales report for a sales director
> in `C:\pbip`, named `VentesAgent`.

## 1. Claude profiles the data

`profile_data(data_dir)` returns what a spec can refer to:

```json
{
  "tables": [
    {"name": "Ventes", "role": "fact", "rows": 2000,
     "columns": [{"name": "ClientID", "hidden": true}, {"name": "Quantité", "type": "int64"},
                 {"name": "Montant", "type": "double", "format": "#,##0.00 €"}],
     "measures": [{"name": "Total Montant"}, {"name": "Nb Ventes"}, {"name": "Total Montant Var % N-1"}]},
    {"name": "Clients", "role": "dimension", "columns": [{"name": "Région", "distinct": 5}, {"name": "Segment", "distinct": 2}]},
    {"name": "Produits", "role": "dimension", "columns": [{"name": "Produit", "distinct": 25}, {"name": "Catégorie", "distinct": 4}]},
    {"name": "Calendrier", "role": "date"}
  ],
  "relationships": [{"from": "Ventes[ClientID]", "to": "Clients[ClientID]"},
                    {"from": "Ventes[ProduitID]", "to": "Produits[ProduitID]"},
                    {"from": "Ventes[Date commande]", "to": "Calendrier[Date]"}]
}
```

## 2. Claude writes a spec and validates it

Three pages (Performance, Produits, Clients) and five business measures (average basket, active
customers, revenue per customer, share of revenue, average delivery time). The first
`validate_spec` call answers:

```json
{"valid": false,
 "issues": ["pages[1] 'Produits'.visuals[0]: 'Produits[Produit]' has 25 values, a clusteredBarChart stays readable up to 20, use a tableEx or a column with fewer values"]}
```

Claude replaces the bar chart of 25 products by a ranking table and validates again:

```json
{"valid": true, "issues": [], "pages": [{"name": "Performance", "visuals": 11},
  {"name": "Produits", "visuals": 8}, {"name": "Clients", "visuals": 8}]}
```

This loop is the point of the design: the model decides what the report shows, the tool checks every
name, chart and DAX reference against the data and says what is available instead.

## 3. Claude generates the project

`generate_report(data_dir, spec, output_dir="C:\pbip", name="VentesAgent")`:

```json
{"pbip_file": "C:\\pbip\\VentesAgent\\VentesAgent.pbip",
 "data_folder_parameter": "C:\\pbip\\VentesAgent\\data\\",
 "pages": ["Performance", "Produits", "Clients"],
 "measures": ["Total Montant", "...", "Panier moyen", "Clients actifs", "CA par client", "Part du CA",
              "Délai de livraison moyen"],
 "next_steps": "Open the .pbip in Power BI Desktop, then click Refresh (the project opens without data)."}
```

The data is copied next to the project; Power BI reads it from there after *Refresh*.

## What Claude never does

It never writes TMDL or PBIR. It writes a spec (pages, measures, theme, highlights), and
pbip-generator, which is deterministic and tested, writes every file. With `PBIP_ALLOWED_ROOTS` set,
the server also refuses any path outside the folders you allowed.
