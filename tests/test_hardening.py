"""Writing safely (overwrite, project names), explicit input errors and sampled inference."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import pbip_generator.inference as inference
from pbip_generator import DataError, ProjectNameError, infer_project, write_project
from pbip_generator.builder import check_project_name
from pbip_generator.cli import main
from pbip_generator.mcp_server import generate_report, profile_data

ROOT = Path(__file__).resolve().parents[1]
SPEC = yaml.safe_load((ROOT / "examples" / "ventes" / "report.yaml").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Overwrite must not delete the data it regenerates from
# --------------------------------------------------------------------------- #
def test_overwrite_from_the_project_own_data_keeps_the_data(example_data, tmp_path):
    out = tmp_path / "out"
    root = write_project(infer_project(example_data, "Ventes"), out, copy_data=True)
    own_data = root / "data"
    before = sorted(p.name for p in own_data.iterdir())

    project = infer_project(own_data, "Ventes")
    assert write_project(project, out, overwrite=True, copy_data=True) == root
    assert sorted(p.name for p in own_data.iterdir()) == before
    assert (root / "Ventes.pbip").is_file()
    assert (own_data / "ventes.csv").read_text(encoding="utf-8") == (example_data / "ventes.csv").read_text(
        encoding="utf-8"
    )


def test_mcp_regenerates_from_the_copied_data(example_data, tmp_path):
    first = generate_report(str(example_data), SPEC, str(tmp_path))
    data = Path(first["project_folder"]) / "data"
    second = generate_report(str(data), SPEC, str(tmp_path), overwrite=True)
    assert second["project_folder"] == first["project_folder"]
    assert (data / "clients.csv").is_file() and Path(second["pbip_file"]).is_file()


# --------------------------------------------------------------------------- #
# Project names come from a language model: they must stay plain folder names
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name", ["../escaped", "..", ".", "a/b", "a\\b", "C:evil", "", " Ventes", "Ventes.", "CON", "nul.txt", "x?"]
)
def test_unsafe_project_names_are_refused(name):
    with pytest.raises(ProjectNameError):
        check_project_name(name)


@pytest.mark.parametrize("name", ["Ventes", "Ventes 2026", "VCT_Scouting", "Équipes-v2", "rapport.final"])
def test_plain_project_names_are_accepted(name):
    check_project_name(name)


@pytest.mark.parametrize("name", ["..", "../escaped", "."])
def test_unsafe_name_writes_and_deletes_nothing(example_data, tmp_path, name):
    out = tmp_path / "out"
    out.mkdir()
    sentinel_out, sentinel_parent = out / "keep.txt", tmp_path / "keep.txt"
    sentinel_out.write_text("x")
    sentinel_parent.write_text("x")
    project = infer_project(example_data, "Ventes")
    project.name = name
    with pytest.raises(ProjectNameError):
        write_project(project, out, overwrite=True, copy_data=True)
    assert sentinel_out.exists() and sentinel_parent.exists()
    assert not (tmp_path / "escaped").exists()


def test_mcp_refuses_an_escaping_name(example_data, tmp_path):
    with pytest.raises(ProjectNameError):
        generate_report(str(example_data), SPEC, str(tmp_path / "out"), name="../escaped")
    assert not (tmp_path / "escaped").exists()


def test_cli_reports_a_bad_name(example_data, tmp_path, capsys):
    assert main(["build", str(example_data), "-o", str(tmp_path), "-n", "../x"]) == 1
    assert "Invalid project name" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Input errors are messages, bugs keep their traceback
# --------------------------------------------------------------------------- #
def test_cli_lets_internal_errors_through(example_data, tmp_path, monkeypatch):
    import pbip_generator.cli as cli

    def broken(*args, **kwargs):
        raise KeyError("internal")

    monkeypatch.setattr(cli, "infer_project", broken)
    with pytest.raises(KeyError):
        main(["build", str(example_data), "-o", str(tmp_path)])


def test_unknown_column_in_config_is_a_config_error(example_data, tmp_path, capsys):
    config = tmp_path / "c.yaml"
    config.write_text("tables:\n  Ventes:\n    hide: [Nope]\n", encoding="utf-8")
    assert main(["build", str(example_data), "-c", str(config), "-o", str(tmp_path / "o")]) == 1
    assert "Column 'Nope' not found in table 'Ventes'" in capsys.readouterr().err


def test_invalid_yaml_is_reported(example_data, tmp_path, capsys):
    for flag in ("-c", "--spec"):
        bad = tmp_path / f"bad{flag}.yaml"
        bad.write_text("tables: [unclosed\n", encoding="utf-8")
        assert main(["build", str(example_data), flag, str(bad), "-o", str(tmp_path / "o")]) == 1
        assert "nvalid YAML" in capsys.readouterr().err


def test_unreadable_excel_is_a_data_error(tmp_path):
    (tmp_path / "broken.xlsx").write_bytes(b"not a zip file")
    with pytest.raises(DataError, match="Cannot read broken.xlsx"):
        infer_project(tmp_path, "T")


def test_two_sources_with_the_same_table_name(tmp_path):
    (tmp_path / "ventes.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / "Ventes.txt").write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(DataError, match="same table name 'Ventes'"):
        infer_project(tmp_path, "T")


# --------------------------------------------------------------------------- #
# Large files: inference on a sample, rows counted in full
# --------------------------------------------------------------------------- #
def test_large_files_are_sampled_and_counted(example_data, monkeypatch):
    monkeypatch.setattr(inference, "SAMPLE_ROWS", 50)
    monkeypatch.setattr(inference, "CHUNK_ROWS", 300)
    project = infer_project(example_data, "Ventes")
    ventes, clients = project.table("Ventes"), project.table("Clients")
    assert ventes.sampled and ventes.row_count == 2000
    assert clients.sampled and clients.row_count == 60
    # Keys are checked on the sample: a sampled dimension keeps its relationships.
    assert ("Ventes", "Clients") in {(r.from_table, r.to_table) for r in project.relationships}
    assert not project.table("Produits").sampled  # 25 rows: read in full
    profile = {t["name"]: t for t in profile_data(str(example_data))["tables"]}
    assert profile["Ventes"]["sampled"] is True and profile["Ventes"]["rows"] == 2000


def test_small_files_are_read_in_full(example_data):
    project = infer_project(example_data, "Ventes")
    assert not any(t.sampled for t in project.tables)
    assert project.table("Ventes").row_count == 2000


def test_large_excel_dimension_keeps_its_relationship(tmp_path, monkeypatch):
    import pandas as pd

    clients = pd.DataFrame({"ClientID": range(1, 101), "Nom": [f"C{i}" for i in range(1, 101)]})
    ventes = pd.DataFrame({"VenteID": range(1, 301), "ClientID": [100 - i % 100 for i in range(300)], "Montant": 1.5})
    clients.to_excel(tmp_path / "Clients.xlsx", index=False)
    ventes.to_csv(tmp_path / "Ventes.csv", index=False)
    monkeypatch.setattr(inference, "SAMPLE_ROWS", 20)
    project = infer_project(tmp_path, "T")
    assert project.table("Clients").sampled and project.table("Clients").row_count == 100
    assert ("Ventes", "ClientID", "Clients", "ClientID") in {
        (r.from_table, r.from_column, r.to_table, r.to_column) for r in project.relationships
    }


# --------------------------------------------------------------------------- #
# MCP: the model chooses paths, the server only accepts PBIP_ALLOWED_ROOTS
# --------------------------------------------------------------------------- #
def test_mcp_refuses_everything_without_allowed_roots(example_data, tmp_path, monkeypatch):
    from pbip_generator import AccessError

    monkeypatch.delenv("PBIP_ALLOWED_ROOTS")
    with pytest.raises(AccessError, match="PBIP_ALLOWED_ROOTS is not set"):
        profile_data(str(example_data))


def test_mcp_reads_and_writes_only_inside_allowed_roots(example_data, tmp_path, monkeypatch):
    import os

    from pbip_generator import AccessError
    from pbip_generator.mcp_server import validate_spec

    allowed, elsewhere = tmp_path / "allowed", tmp_path / "elsewhere"
    allowed.mkdir()
    elsewhere.mkdir()
    data = allowed / "data"
    data.mkdir()
    for f in example_data.iterdir():
        (data / f.name).write_bytes(f.read_bytes())
    monkeypatch.setenv("PBIP_ALLOWED_ROOTS", os.pathsep.join([str(allowed), str(tmp_path / "other")]))

    assert profile_data(str(data))["tables"]
    for path in (str(example_data), str(allowed / ".." / "elsewhere"), str(elsewhere)):
        with pytest.raises(AccessError, match="outside the allowed folders"):
            profile_data(path)
        with pytest.raises(AccessError):
            validate_spec(path, SPEC)
    with pytest.raises(AccessError, match="output folder"):
        generate_report(str(data), SPEC, str(elsewhere))
    assert not any(elsewhere.iterdir())
    assert Path(generate_report(str(data), SPEC, str(allowed / "out"))["pbip_file"]).is_file()


def test_mcp_tool_reports_access_errors(example_data, tmp_path, monkeypatch):
    import asyncio

    pytest.importorskip("mcp")
    from mcp import Client

    from pbip_generator.mcp_server import create_server

    monkeypatch.setenv("PBIP_ALLOWED_ROOTS", str(tmp_path / "nowhere"))

    async def run():
        async with Client(create_server()) as client:
            return await client.call_tool("profile_data", {"data_dir": str(example_data)})

    result = asyncio.run(run())
    assert result.is_error and "outside the allowed folders" in result.content[0].text


# --------------------------------------------------------------------------- #
# Atomic write: a crash while writing leaves the previous project as it was
# --------------------------------------------------------------------------- #
def _snapshot(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


@pytest.mark.parametrize("fail_at", ["write", "copy"])
def test_crash_while_writing_keeps_the_previous_project(example_data, tmp_path, monkeypatch, fail_at):
    import shutil

    out = tmp_path / "out"
    root = write_project(infer_project(example_data, "Ventes"), out, copy_data=True)
    before = _snapshot(root)

    if fail_at == "write":
        original, calls = Path.write_text, {"n": 0}

        def failing_write(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 10:
                raise OSError("disk full")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", failing_write)
    else:

        def failing_copy(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(shutil, "copytree", failing_copy)

    with pytest.raises(OSError, match="disk full"):
        write_project(infer_project(example_data, "Ventes"), out, overwrite=True, copy_data=True)
    assert _snapshot(root) == before
    assert [p.name for p in out.iterdir()] == ["Ventes"]  # no staging folder left behind


def test_locked_previous_project_is_left_in_place(example_data, tmp_path, monkeypatch):
    out = tmp_path / "out"
    root = write_project(infer_project(example_data, "Ventes"), out)
    before = _snapshot(root)
    original = Path.rename

    def locked(self, target):
        if self == root:
            raise PermissionError("file in use")
        return original(self, target)

    monkeypatch.setattr(Path, "rename", locked)
    with pytest.raises(PermissionError):
        write_project(infer_project(example_data, "Ventes"), out, overwrite=True)
    assert _snapshot(root) == before and [p.name for p in out.iterdir()] == ["Ventes"]


def test_failed_swap_puts_the_previous_project_back(example_data, tmp_path, monkeypatch):
    out = tmp_path / "out"
    root = write_project(infer_project(example_data, "Ventes"), out)
    before = _snapshot(root)
    original = Path.rename

    def failing_second_rename(self, target):
        if Path(target) == root and self.name.startswith(".pbip-") and not self.name.endswith("-old"):
            raise PermissionError("antivirus scan")
        return original(self, target)

    monkeypatch.setattr(Path, "rename", failing_second_rename)
    with pytest.raises(PermissionError):
        write_project(infer_project(example_data, "Ventes"), out, overwrite=True)
    assert _snapshot(root) == before and [p.name for p in out.iterdir()] == ["Ventes"]
