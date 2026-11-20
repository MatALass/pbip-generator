"""MCP server: the tools as plain functions, then through an in-process MCP client."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import yaml

from pbip_generator.mcp_server import generate_report, get_spec_schema, profile_data, validate_spec

ROOT = Path(__file__).resolve().parents[1]
SPEC = yaml.safe_load((ROOT / "examples" / "ventes" / "report.yaml").read_text(encoding="utf-8"))


def test_profile_lists_tables_relationships_and_measures(example_data):
    result = profile_data(str(example_data))
    tables = {t["name"]: t for t in result["tables"]}
    assert set(tables) == {"Clients", "Produits", "Ventes", "Calendrier"}
    assert tables["Ventes"]["role"] == "fact"
    client_id = next(c for c in tables["Ventes"]["columns"] if c["name"] == "ClientID")
    assert client_id["hidden"] is True
    assert "Total Montant" in {m["name"] for m in tables["Ventes"]["measures"]}
    assert {"from": "Ventes[ClientID]", "to": "Clients[ClientID]"} in result["relationships"]
    json.dumps(result)  # the MCP client receives JSON


def test_schema_has_the_spec_and_the_templates():
    result = get_spec_schema()
    assert "PageSpec" in result["schema"]["$defs"]
    assert result["template_slots"]["kpis_2x2"] == 4


def test_validate_returns_issues_instead_of_raising(example_data):
    bad = {**SPEC, "pages": [{**SPEC["pages"][0], "kpis": ["[CA]"]}]}
    result = validate_spec(str(example_data), bad)
    assert result["valid"] is False and "unknown measure [CA]" in result["issues"][0]
    ok = validate_spec(str(example_data), SPEC)
    assert ok == {"valid": True, "issues": [], "pages": ok["pages"]}
    assert [p["name"] for p in ok["pages"]] == ["Synthèse", "Produits", "Clients"]


def test_validate_reports_schema_errors(example_data):
    result = validate_spec(str(example_data), {"audience": "daf"})
    assert result["valid"] is False
    assert any(i.startswith("business_question") for i in result["issues"])


def test_generate_points_power_bi_to_the_copied_data(example_data, tmp_path):
    result = generate_report(str(example_data), SPEC, str(tmp_path))
    root = Path(result["project_folder"])
    assert root == tmp_path.resolve() / "Ventes"
    assert (root / "Ventes.pbip").is_file() and (root / "data" / "ventes.csv").is_file()
    assert result["data_folder_parameter"].rstrip("\\/") == str(root / "data")
    assert "Panier moyen" in result["measures"]


def test_generate_refuses_to_overwrite(example_data, tmp_path):
    generate_report(str(example_data), SPEC, str(tmp_path))
    with pytest.raises(FileExistsError):
        generate_report(str(example_data), SPEC, str(tmp_path))


def _call(server, name: str, arguments: dict):
    from mcp import Client

    async def run():
        async with Client(server) as client:
            return await client.call_tool(name, arguments)

    return asyncio.run(run())


def test_server_exposes_the_four_tools():
    pytest.importorskip("mcp")
    from mcp import Client

    from pbip_generator.mcp_server import create_server

    async def run():
        async with Client(create_server()) as client:
            return (await client.list_tools()).tools

    tools = {t.name: t for t in asyncio.run(run())}
    assert set(tools) == {"profile_data", "get_spec_schema", "validate_spec", "generate_report"}
    assert "Absolute path" in tools["generate_report"].input_schema["properties"]["data_dir"]["description"]
    assert tools["generate_report"].input_schema["required"] == ["data_dir", "spec", "output_dir"]


def test_server_turns_expected_failures_into_tool_errors(example_data, tmp_path):
    pytest.importorskip("mcp")
    from pbip_generator.mcp_server import create_server

    result = _call(create_server(), "profile_data", {"data_dir": str(tmp_path / "missing")})
    assert result.is_error and "Data folder not found" in result.content[0].text
    bad = {**SPEC, "pages": [{**SPEC["pages"][0], "template": "kpis_2"}]}
    result = _call(
        create_server(),
        "generate_report",
        {"data_dir": str(example_data), "spec": bad, "output_dir": str(tmp_path / "x")},
    )
    assert result.is_error and "holds 2 visual(s), got 3" in result.content[0].text


def test_server_generates_a_project(example_data, tmp_path):
    pytest.importorskip("mcp")
    from pbip_generator.mcp_server import create_server

    args = {"data_dir": str(example_data), "spec": SPEC, "output_dir": str(tmp_path), "name": "Demo"}
    result = _call(create_server(), "generate_report", args)
    assert not result.is_error
    assert result.structured_content["pbip_file"].endswith("Demo.pbip")
    assert (tmp_path / "Demo" / "Demo.pbip").is_file()
