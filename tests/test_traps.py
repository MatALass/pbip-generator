"""Data that breaks naive generators: empty files, duplicate or blank headers, accents and spaces,
Windows-1252 encoding, Excel workbooks with several sheets, keys just below the match threshold,
and a one-million-row file."""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import pytest

from pbip_generator import DataError, infer_project, render_project
from pbip_generator.model import DataType, TableRole


def _folder(tmp_path: Path, files: dict[str, str | bytes]) -> Path:
    folder = tmp_path / "data"
    folder.mkdir()
    for name, content in files.items():
        (folder / name).write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return folder


def _rels(project) -> set[tuple[str, str, str, str]]:
    return {(r.from_table, r.from_column, r.to_table, r.to_column) for r in project.relationships}


# --------------------------------------------------------------------------- #
# Empty files and headers
# --------------------------------------------------------------------------- #
def test_empty_csv_is_reported(tmp_path):
    with pytest.raises(DataError, match="vide.csv is empty"):
        infer_project(_folder(tmp_path, {"vide.csv": "", "ventes.csv": "a,b\n1,2\n"}), "T")


def test_header_only_csv_is_an_empty_text_table(tmp_path):
    project = infer_project(_folder(tmp_path, {"clients.csv": "ID,Nom\n", "ventes.csv": "a,b\n1,2\n"}), "T")
    clients = project.table("Clients")
    assert clients.row_count == 0 and [c.data_type for c in clients.columns] == [DataType.STRING] * 2
    render_project(project)


@pytest.mark.parametrize(
    ("header", "message"),
    [
        ("Montant,Client,Montant", "columns 'Montant' and 'Montant' have the same name"),
        ("Montant,Client,montant", "columns 'Montant' and 'montant' have the same name"),
        ("Montant,,Client", "column 2 has no header"),
    ],
)
def test_duplicate_or_blank_headers_are_reported(tmp_path, header, message):
    with pytest.raises(DataError, match=message):
        infer_project(_folder(tmp_path, {"ventes.csv": f"{header}\n1,a,2\n"}), "T")


def test_trailing_separator_is_not_a_blank_header(tmp_path):
    project = infer_project(_folder(tmp_path, {"ventes.csv": "Montant;Client;\n1;a;\n"}), "T")
    assert [c.name for c in project.table("Ventes").columns][:2] == ["Montant", "Client"]


def test_duplicate_headers_in_an_excel_sheet(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    with pd.ExcelWriter(folder / "classeur.xlsx") as writer:
        pd.DataFrame([[1, 2]], columns=["CA", "ca"]).to_excel(writer, sheet_name="Ventes", index=False)
        pd.DataFrame([[1]], columns=["ID"]).to_excel(writer, sheet_name="Autre", index=False)
    with pytest.raises(DataError, match=r"classeur.xlsx \(sheet Ventes\): columns 'CA' and 'ca'"):
        infer_project(folder, "T")


# --------------------------------------------------------------------------- #
# Names, encodings, workbooks
# --------------------------------------------------------------------------- #
def test_accents_and_spaces_in_table_and_column_names(tmp_path):
    folder = _folder(
        tmp_path,
        {
            "Équipes clients.csv": "Équipe ID,Nom de l'équipe\n1,Fnatic\n2,LOUD\n",
            "Matchs joués.csv": "Équipe ID,Score final\n1,13\n2,9\n1,11\n",
        },
    )
    project = infer_project(folder, "T")
    assert ("Matchs joués", "Équipe ID", "Équipes clients", "Équipe ID") in _rels(project)
    files = render_project(project)
    measures = next(v for k, v in files.items() if k.endswith("tables/Matchs joués.tmdl"))
    assert "COUNTROWS('Matchs joués')" in measures and "SUM('Matchs joués'[Score final])" in measures


def test_windows_1252_csv_with_french_numbers(tmp_path):
    content = "Région;Montant;Date\nÎle-de-France;1 234,50;31/12/2024\nCôte-d'Or;3,25;01/01/2025\n"
    project = infer_project(_folder(tmp_path, {"ventes.csv": content.encode("cp1252")}), "T")
    ventes = project.table("Ventes")
    assert ventes.source.encoding == 1252 and ventes.source.culture == "fr-FR"
    assert ventes.column("Montant").data_type == DataType.DOUBLE
    assert ventes.column("Date").data_type == DataType.DATETIME
    assert ventes.column("Région").distinct_count == 2


def test_excel_with_several_sheets_and_an_empty_one(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    with pd.ExcelWriter(folder / "classeur.xlsx") as writer:
        pd.DataFrame({"MagasinID": [1, 2], "Ville": ["Paris", "Lyon"]}).to_excel(
            writer, sheet_name="Magasins", index=False
        )
        pd.DataFrame({"MagasinID": [1, 2, 2], "CA": [10.5, 20.0, 7.25]}).to_excel(
            writer, sheet_name="Ventes", index=False
        )
        pd.DataFrame().to_excel(writer, sheet_name="Notes", index=False)
    project = infer_project(folder, "T")
    assert {t.name for t in project.tables} == {"Magasins", "Ventes"}
    assert {t.source.sheet for t in project.tables} == {"Magasins", "Ventes"}
    assert ("Ventes", "MagasinID", "Magasins", "MagasinID") in _rels(project)


# --------------------------------------------------------------------------- #
# Relationship threshold: 90 % of the many-side keys must exist on the one side
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("known_clients", "linked"), [(89, False), (90, True), (91, True)])
def test_relationship_needs_90_percent_of_keys(tmp_path, known_clients, linked):
    clients = "ClientID,Nom\n" + "\n".join(f"{i},C{i}" for i in range(1, known_clients + 1))
    ventes = "ClientID,Montant\n" + "\n".join(f"{i % 100 + 1},{i}" for i in range(1000))  # 100 clients
    project = infer_project(_folder(tmp_path, {"clients.csv": clients, "ventes.csv": ventes}), "T")
    assert (("Ventes", "ClientID", "Clients", "ClientID") in _rels(project)) is linked
    if linked:
        assert project.table("Ventes").role == TableRole.FACT


# --------------------------------------------------------------------------- #
# Volume
# --------------------------------------------------------------------------- #
ONE_MILLION = 1_000_000
MAX_SECONDS = 60  # CI runners are slower than a laptop: about 4 s locally


def test_one_million_rows(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    n = ONE_MILLION
    pd.DataFrame(
        {
            "VenteID": range(1, n + 1),
            "ClientID": [i % 5000 + 1 for i in range(n)],
            "Date": pd.date_range("2020-01-01", periods=n, freq="min").strftime("%Y-%m-%d"),
            "Montant": [round(i % 997 * 1.25, 2) for i in range(n)],
        }
    ).to_csv(folder / "ventes.csv", index=False)
    pd.DataFrame({"ClientID": range(1, 5001), "Nom": [f"Client {i}" for i in range(1, 5001)]}).to_csv(
        folder / "clients.csv", index=False
    )

    start = time.perf_counter()
    project = infer_project(folder, "Volume")
    render_project(project)
    elapsed = time.perf_counter() - start

    ventes = project.table("Ventes")
    assert ventes.row_count == n and ventes.sampled
    assert ventes.column("Montant").data_type == DataType.DOUBLE
    assert ("Ventes", "ClientID", "Clients", "ClientID") in _rels(project)
    assert project.date_table is not None
    assert elapsed < MAX_SECONDS, f"inference took {elapsed:.1f} s"
