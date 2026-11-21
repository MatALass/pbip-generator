"""Build the fuel price example from Etalab's public history of the French fuel price feed.

Source: https://github.com/etalab/prix-carburants-data (MIT), a daily copy of the government
feed "Prix des carburants en France" (data.gouv.fr, Licence Ouverte). Each daily file lists every
station with its last price per fuel and the time that price was last updated.

The example keeps the stations of one region (Ile-de-France by default) and two snapshots per
month, from September 2022 to November 2023. A price is kept only if it was updated in the 7 days
before the snapshot: a station that stopped updating would otherwise repeat an old price for
months.

    python examples/carburants/fetch_data.py                 # writes examples/carburants/data
    python examples/carburants/fetch_data.py --region 84 -o /tmp/ara

Standard library only. Downloads about 200 MB (29 files of 7 MB), cached in --cache.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

# Pinned commit: the files never change under the example.
COMMIT = "937e5edb2cea67a5cde46494287d26aa70026a07"
BASE = f"https://raw.githubusercontent.com/etalab/prix-carburants-data/{COMMIT}/dist/historique/"

# First available daily file on or after the 1st and the 15th of each month.
SNAPSHOTS = [
    "2022-09-15", "2022-10-01", "2022-10-15", "2022-11-01", "2022-11-16", "2022-12-01",
    "2022-12-15", "2023-01-01", "2023-01-15", "2023-02-01", "2023-02-15", "2023-03-01",
    "2023-03-15", "2023-04-01", "2023-04-15", "2023-05-01", "2023-05-16", "2023-06-01",
    "2023-06-15", "2023-07-01", "2023-07-15", "2023-08-07", "2023-08-15", "2023-09-01",
    "2023-09-15", "2023-10-02", "2023-10-15", "2023-11-01", "2023-11-15",
]  # fmt: skip

MAX_AGE_DAYS = 7

FUELS = {
    # code in the feed: (label, family)
    "Gazole": ("Gazole (B7)", "Diesel"),
    "SP95": ("Sans plomb 95 (E5)", "Essence"),
    "E10": ("Sans plomb 95-E10", "Essence"),
    "SP98": ("Sans plomb 98", "Essence"),
    "E85": ("Superéthanol E85", "Biocarburant"),
    "GPLc": ("GPL carburant", "Gaz"),
}

REGIONS = {
    "11": "Île-de-France", "24": "Centre-Val de Loire", "27": "Bourgogne-Franche-Comté",
    "28": "Normandie", "32": "Hauts-de-France", "44": "Grand Est", "52": "Pays de la Loire",
    "53": "Bretagne", "75": "Nouvelle-Aquitaine", "76": "Occitanie",
    "84": "Auvergne-Rhône-Alpes", "93": "Provence-Alpes-Côte d'Azur", "94": "Corse",
}  # fmt: skip

DEPARTEMENTS = {
    "01": ("Ain", "84"), "02": ("Aisne", "32"), "03": ("Allier", "84"),
    "04": ("Alpes-de-Haute-Provence", "93"), "05": ("Hautes-Alpes", "93"),
    "06": ("Alpes-Maritimes", "93"), "07": ("Ardèche", "84"), "08": ("Ardennes", "44"),
    "09": ("Ariège", "76"), "10": ("Aube", "44"), "11": ("Aude", "76"), "12": ("Aveyron", "76"),
    "13": ("Bouches-du-Rhône", "93"), "14": ("Calvados", "28"), "15": ("Cantal", "84"),
    "16": ("Charente", "75"), "17": ("Charente-Maritime", "75"), "18": ("Cher", "24"),
    "19": ("Corrèze", "75"), "2A": ("Corse-du-Sud", "94"), "2B": ("Haute-Corse", "94"),
    "21": ("Côte-d'Or", "27"), "22": ("Côtes-d'Armor", "53"), "23": ("Creuse", "75"),
    "24": ("Dordogne", "75"), "25": ("Doubs", "27"), "26": ("Drôme", "84"), "27": ("Eure", "28"),
    "28": ("Eure-et-Loir", "24"), "29": ("Finistère", "53"), "30": ("Gard", "76"),
    "31": ("Haute-Garonne", "76"), "32": ("Gers", "76"), "33": ("Gironde", "75"),
    "34": ("Hérault", "76"), "35": ("Ille-et-Vilaine", "53"), "36": ("Indre", "24"),
    "37": ("Indre-et-Loire", "24"), "38": ("Isère", "84"), "39": ("Jura", "27"),
    "40": ("Landes", "75"), "41": ("Loir-et-Cher", "24"), "42": ("Loire", "84"),
    "43": ("Haute-Loire", "84"), "44": ("Loire-Atlantique", "52"), "45": ("Loiret", "24"),
    "46": ("Lot", "76"), "47": ("Lot-et-Garonne", "75"), "48": ("Lozère", "76"),
    "49": ("Maine-et-Loire", "52"), "50": ("Manche", "28"), "51": ("Marne", "44"),
    "52": ("Haute-Marne", "44"), "53": ("Mayenne", "52"), "54": ("Meurthe-et-Moselle", "44"),
    "55": ("Meuse", "44"), "56": ("Morbihan", "53"), "57": ("Moselle", "44"),
    "58": ("Nièvre", "27"), "59": ("Nord", "32"), "60": ("Oise", "32"), "61": ("Orne", "28"),
    "62": ("Pas-de-Calais", "32"), "63": ("Puy-de-Dôme", "84"),
    "64": ("Pyrénées-Atlantiques", "75"), "65": ("Hautes-Pyrénées", "76"),
    "66": ("Pyrénées-Orientales", "76"), "67": ("Bas-Rhin", "44"), "68": ("Haut-Rhin", "44"),
    "69": ("Rhône", "84"), "70": ("Haute-Saône", "27"), "71": ("Saône-et-Loire", "27"),
    "72": ("Sarthe", "52"), "73": ("Savoie", "84"), "74": ("Haute-Savoie", "84"),
    "75": ("Paris", "11"), "76": ("Seine-Maritime", "28"), "77": ("Seine-et-Marne", "11"),
    "78": ("Yvelines", "11"), "79": ("Deux-Sèvres", "75"), "80": ("Somme", "32"),
    "81": ("Tarn", "76"), "82": ("Tarn-et-Garonne", "76"), "83": ("Var", "93"),
    "84": ("Vaucluse", "93"), "85": ("Vendée", "52"), "86": ("Vienne", "75"),
    "87": ("Haute-Vienne", "75"), "88": ("Vosges", "44"), "89": ("Yonne", "27"),
    "90": ("Territoire de Belfort", "27"), "91": ("Essonne", "11"),
    "92": ("Hauts-de-Seine", "11"), "93": ("Seine-Saint-Denis", "11"),
    "94": ("Val-de-Marne", "11"), "95": ("Val-d'Oise", "11"),
}  # fmt: skip

_LOWER = {"sur", "sous", "le", "la", "les", "de", "du", "des", "en", "et", "lès", "lez", "aux", "au"}


def commune_name(raw: str) -> str:
    """'saint-brice-sous-forêt' -> 'Saint-Brice-sous-Forêt' (the feed is lower case)."""
    words = []
    for i, part in enumerate(raw.strip().replace("  ", " ").split(" ")):
        pieces = []
        for j, p in enumerate(part.split("-")):
            first = i == 0 and j == 0
            pieces.append(p if (p in _LOWER and not first) else p[:1].upper() + p[1:])
        words.append("-".join(pieces))
    return " ".join(words)


def split_city(cpl_adr: str) -> tuple[str, str]:
    """'77100 meaux' -> ('77100', 'Meaux')."""
    code, _, city = cpl_adr.strip().partition(" ")
    return (code, commune_name(city)) if code.isdigit() and len(code) == 5 else ("", commune_name(cpl_adr))


def load(date: str, cache: Path) -> list[dict]:
    path = cache / f"{date}.json"
    if not path.exists():
        print(f"  download {date}", file=sys.stderr)
        with urllib.request.urlopen(BASE + f"{date}.json", timeout=120) as r:
            path.write_bytes(r.read())
    return json.loads(path.read_text(encoding="utf-8"))["features"]


def build(region: str, out: Path, cache: Path) -> dict[str, int]:
    deps = {code for code, (_, reg) in DEPARTEMENTS.items() if reg == region}
    if not deps:
        raise SystemExit(f"unknown region code {region!r}, expected one of {sorted(REGIONS)}")
    cache.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    stations: dict[str, dict] = {}
    rows: list[tuple[str, str, str, float]] = []
    stats = {"prices_seen": 0, "stale": 0, "out_of_range": 0}
    for date in SNAPSHOTS:
        day = dt.date.fromisoformat(date)
        for feature in load(date, cache):
            p = feature["properties"]
            if p.get("dep") not in deps:
                continue
            sid = str(p["id"])
            lon, lat = (feature.get("geometry") or {}).get("coordinates") or (None, None)
            postcode, city = split_city(p.get("cpl_adr") or "")
            # Latest snapshot wins: addresses get corrected over time.
            stations[sid] = {
                "StationID": sid,
                "Adresse": (p.get("adr") or "").strip(),
                "Code postal": postcode,
                "Commune": city,
                "Département": DEPARTEMENTS[p["dep"]][0],
                "Région": REGIONS[region],
                "Latitude": lat,
                "Longitude": lon,
            }
            for fuel in FUELS:
                value, updated = p.get(fuel), p.get(f"{fuel}_m")
                if value in (None, "", "N") or not updated:
                    continue
                stats["prices_seen"] += 1
                age = (day - dt.date.fromisoformat(updated[:10])).days
                if not 0 <= age <= MAX_AGE_DAYS:
                    stats["stale"] += 1
                    continue
                price = float(value)
                if not 0.5 <= price <= 4.0:  # a few stations type prices in cents or by mistake
                    stats["out_of_range"] += 1
                    continue
                rows.append((date, sid, fuel, round(price, 3)))

    used = {sid for _, sid, _, _ in rows}
    with open(out / "stations.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(next(iter(stations.values()))), lineterminator="\n")
        w.writeheader()
        for sid in sorted(used):
            w.writerow(stations[sid])
    with open(out / "carburants.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Carburant", "Libellé carburant", "Famille"])
        for code, (label, family) in FUELS.items():
            w.writerow([code, label, family])
    with open(out / "releves.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Date relevé", "StationID", "Carburant", "Prix au litre"])
        w.writerows(sorted(rows))
    stats.update(stations=len(used), rows=len(rows), snapshots=len(SNAPSHOTS))
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--region", default="11", help="INSEE region code (default 11, Ile-de-France)")
    parser.add_argument("-o", "--out", type=Path, default=Path(__file__).parent / "data")
    parser.add_argument("--cache", type=Path, default=Path(".cache/prix-carburants"))
    args = parser.parse_args()
    stats = build(args.region, args.out, args.cache)
    kept = stats["rows"] / stats["prices_seen"] if stats["prices_seen"] else 0
    print(
        f"{stats['rows']} prices kept out of {stats['prices_seen']} ({kept:.1%}), "
        f"{stats['stale']} stale, {stats['out_of_range']} out of range, "
        f"{stats['stations']} stations, {stats['snapshots']} snapshots -> {args.out}"
    )


if __name__ == "__main__":
    main()
