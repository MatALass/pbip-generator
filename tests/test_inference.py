from __future__ import annotations

from pathlib import Path

import pandas as pd

from pbip_generator.inference import infer_project, is_key_like, normalize
from pbip_generator.model import DataType, TableRole


def test_normalize_and_keys():
    assert normalize("Client_ID") == "clientid"
    assert normalize("Région") == "region"
    assert is_key_like("ClientID") and is_key_like("code_postal")
    assert not is_key_like("Montant")


def test_example_star_schema(example_data: Path):
    p = infer_project(example_data, "Ventes")
    roles = {t.name: t.role for t in p.tables}
    assert roles == {
        "Clients": TableRole.DIMENSION,
        "Produits": TableRole.DIMENSION,
        "Ventes": TableRole.FACT,
        "Calendrier": TableRole.DATE,
    }
    rels = {(r.from_table, r.from_column, r.to_table, r.to_column, r.is_active) for r in p.relationships}
    assert ("Ventes", "ClientID", "Clients", "ClientID", True) in rels
    assert ("Ventes", "ProduitID", "Produits", "ProduitID", True) in rels
    assert ("Ventes", "Date commande", "Calendrier", "Date", True) in rels
    assert ("Ventes", "Date livraison", "Calendrier", "Date", False) in rels

    ventes = p.table("Ventes")
    assert ventes.column("Montant").data_type == DataType.DOUBLE
    assert ventes.column("Date commande").data_type == DataType.DATETIME
    assert ventes.column("Date commande").is_date_only
    assert ventes.column("ClientID").is_hidden
    assert ventes.measures[0].name == "Total Montant"  # amounts come first
    assert {"Nb Ventes", "Total Montant N-1", "Total Montant Var % N-1"} <= {m.name for m in ventes.measures}


def test_french_csv(tmp_path: Path):
    d = tmp_path / "fr"
    d.mkdir()
    (d / "achats.csv").write_text(
        "Code;Date;Montant;Libellé\n0012;31/12/2024;1 234,50;Café\n0013;01/01/2025;99,90;Thé\n", encoding="cp1252"
    )
    p = infer_project(d, "Achats")
    t = p.table("Achats")
    assert t.source.delimiter == ";" and t.source.culture == "fr-FR" and t.source.encoding == 1252
    assert t.column("Code").data_type == DataType.STRING  # leading zeros
    assert t.column("Montant").data_type == DataType.DOUBLE
    assert t.column("Date").data_type == DataType.DATETIME
    assert t.role == TableRole.FACT


def test_excel_multi_sheet(tmp_path: Path):
    d = tmp_path / "xl"
    d.mkdir()
    with pd.ExcelWriter(d / "classeur.xlsx") as w:
        pd.DataFrame({"MagasinID": [1, 2], "Ville": ["Paris", "Lyon"]}).to_excel(w, "Magasins", index=False)
        pd.DataFrame(
            {
                "MagasinID": [1, 1, 2],
                "Jour": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-02"]),
                "CA": [10.5, 20.0, 7.25],
            }
        ).to_excel(w, "Ventes", index=False)
    p = infer_project(d, "Magasins")
    assert {t.name for t in p.tables} == {"Magasins", "Ventes", "Calendrier"}
    assert p.table("Ventes").source.kind == "excel"
    assert any(r.from_table == "Ventes" and r.to_table == "Magasins" for r in p.relationships)


def test_single_table_is_fact(tmp_path: Path):
    d = tmp_path / "one"
    d.mkdir()
    (d / "data.csv").write_text("Pays,Valeur\nFR,1.5\nDE,2\n", encoding="utf-8")
    p = infer_project(d, "One")
    assert p.table("Data").role == TableRole.FACT
    assert p.date_table is None


def test_generic_id_matches_table_name(tmp_path: Path):
    d = tmp_path / "ids"
    d.mkdir()
    (d / "magasins.csv").write_text("ID,Ville\n1,Paris\n2,Lyon\n", encoding="utf-8")
    (d / "tickets.csv").write_text("TicketID,MagasinID,Montant\n1,1,10.5\n2,1,3\n3,2,8\n", encoding="utf-8")
    p = infer_project(d, "Tickets")
    assert any(
        (r.from_table, r.from_column, r.to_table, r.to_column) == ("Tickets", "MagasinID", "Magasins", "ID")
        for r in p.relationships
    )
