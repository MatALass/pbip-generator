# Dictionnaire de données : Ventes

Généré par pbip-generator : 4 tables, 8 mesures, 4 relations.

## Tables

| Table | Rôle | Source | Lignes | Colonnes | Mesures |
|---|---|---|---:|---:|---:|
| Ventes | faits | `ventes.csv` | 2 000 | 7 | 8 |
| Clients | dimension | `clients.csv` | 60 | 4 | 0 |
| Produits | dimension | `produits.csv` | 25 | 4 | 0 |
| Calendrier | dates | table générée (Power Query) |  | 8 | 0 |

### Ventes

| Colonne | Type | Format | Masquée |
|---|---|---|---|
| VenteID | int64 |  | oui |
| Date commande | dateTime | `dd/mm/yyyy` | oui |
| Date livraison | dateTime | `dd/mm/yyyy` | oui |
| ClientID | int64 |  | oui |
| ProduitID | int64 |  | oui |
| Quantité | int64 | `#,##0` | non |
| Montant | double | `#,##0.00 €` | non |

### Clients

| Colonne | Type | Format | Masquée |
|---|---|---|---|
| ClientID | int64 |  | oui |
| Nom client | string |  | non |
| Région | string |  | non |
| Segment | string |  | non |

### Produits

| Colonne | Type | Format | Masquée |
|---|---|---|---|
| ProduitID | int64 |  | oui |
| Produit | string |  | non |
| Catégorie | string |  | non |
| Prix unitaire | double | `#,##0.00 €` | non |

### Calendrier

| Colonne | Type | Format | Masquée |
|---|---|---|---|
| Date | dateTime | `dd/mm/yyyy` | non |
| Année | int64 | `0` | non |
| Trimestre | string |  | non |
| Mois numéro | int64 | `0` | oui |
| Mois | string |  | non |
| Année-Mois | string |  | non |
| Jour semaine numéro | int64 | `0` | oui |
| Jour semaine | string |  | non |

## Relations

| De (plusieurs) | Vers (un) | Active |
|---|---|---|
| Ventes[ClientID] | Clients[ClientID] | oui |
| Ventes[ProduitID] | Produits[ProduitID] | oui |
| Ventes[Date commande] | Calendrier[Date] | oui |
| Ventes[Date livraison] | Calendrier[Date] | non |

## Mesures

| Mesure | Table | Dossier | Format | Description |
|---|---|---|---|---|
| Total Montant | Ventes | Base | `#,##0 €` |  |
| Total Quantité | Ventes | Base | `#,##0` |  |
| Nb Ventes | Ventes | Base | `#,##0` |  |
| Total Montant N-1 | Ventes | Temps | `#,##0 €` |  |
| Total Montant Var % N-1 | Ventes | Temps | `0.0 %;-0.0 %;0.0 %` |  |
| Total Montant Cumul annuel | Ventes | Temps | `#,##0 €` |  |
| Panier moyen | Ventes | KPI | `#,##0.00 €` | Montant moyen d'une vente |
| Clients actifs | Ventes | KPI | `#,##0` | Nombre de clients ayant acheté sur la période |

### Total Montant

Expression DAX (Ventes):

```dax
SUM(Ventes[Montant])
```

### Total Quantité

Expression DAX (Ventes):

```dax
SUM(Ventes[Quantité])
```

### Nb Ventes

Expression DAX (Ventes):

```dax
COUNTROWS(Ventes)
```

### Total Montant N-1

Expression DAX (Ventes):

```dax
IF(
    DATEDIFF(MIN(Calendrier[Date]), MAX(Calendrier[Date]), DAY) < 366,
    CALCULATE([Total Montant], SAMEPERIODLASTYEAR(Calendrier[Date]))
)
```

### Total Montant Var % N-1

Expression DAX (Ventes):

```dax
VAR _n = [Total Montant]
VAR _n1 = [Total Montant N-1]
RETURN DIVIDE(_n - _n1, _n1)
```

### Total Montant Cumul annuel

Expression DAX (Ventes):

```dax
TOTALYTD([Total Montant], Calendrier[Date])
```

### Panier moyen

Expression DAX (Ventes):

```dax
DIVIDE([Total Montant], [Nb Ventes])
```

### Clients actifs

Expression DAX (Ventes):

```dax
DISTINCTCOUNT(Ventes[ClientID])
```
