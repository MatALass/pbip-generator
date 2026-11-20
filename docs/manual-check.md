# Manual check in Power BI Desktop

The test suite proves the files are well-formed: the report JSON against Microsoft's Fabric schemas,
the semantic model with TOM (the `tmdl` CI job), the output against frozen golden files. Only Power
BI Desktop proves that the project opens, refreshes and draws what the spec asked for. Run this
checklist before each release and after each Power BI Desktop update, then record the result in
the table at the end and in the README.

## Prepare

```bash
pbip-generator build examples/ventes/data -c examples/ventes/config.yaml -o C:/pbip/check -n VentesAuto --copy-data --overwrite
pbip-generator build examples/ventes/data --spec examples/ventes/report.yaml -o C:/pbip/check -n VentesSpec --copy-data --overwrite
```

For the dark theme, copy `examples/ventes/report.yaml`, add `theme: {preset: dark}` and build it as
`VentesDark`.

## Checklist (for each project)

**Open and refresh**
- [ ] The `.pbip` opens without an error or a repair prompt.
- [ ] *Refresh* loads every table without an error (Home > Refresh).
- [ ] Row counts: Ventes 2,000, Clients 60, Produits 25 (Data view).

**Model**
- [ ] Model view: Ventes in the middle, Clients, Produits and Calendrier around it, one-to-many arrows.
- [ ] `Ventes[Date livraison]` -> `Calendrier[Date]` is inactive (dotted line).
- [ ] Calendrier is marked as date table, Mois sorts January to December.
- [ ] Measures are in their display folders, hidden keys do not show in the field list.
- [ ] `Total Montant` shows in euros; `Total Montant N-1` is blank with no year selected.

**Report**
- [ ] Every page draws every visual: no "Can't display the visual" and no "Fix this" message.
- [ ] Slicers show a dropdown box under their header, not only the header.
- [ ] Clicking a table row or a bar filters the other visuals (not highlight).
- [ ] Spec project: highlights color the right cells; a `single_select` slicer accepts one value.
- [ ] Theme: page background, cards with rounded borders and shadows, readable titles.
- [ ] Save as `.pbix` works (File > Save as).

## Results

| Date | Power BI Desktop | Projects | Result | Notes |
|---|---|---|---|---|
| 2026-11-20 | 2.159.1231.0 (Microsoft Store) | VentesSpec (light), VCT scouting report on real data (dark, 3 pages, highlights) | Pass after fixes | Found and fixed: chart drawing nothing when cross-highlighted, unquoted accented table name in DAX |
