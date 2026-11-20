from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DATA = ROOT / "examples" / "ventes" / "data"
SCHEMA_PREFIX = "https://developer.microsoft.com/json-schemas/fabric/"


def _schemas_dir() -> Path | None:
    """Local clone of github.com/microsoft/json-schemas (its 'fabric' folder)."""
    candidates = [os.environ.get("PBIP_SCHEMAS_DIR"), ROOT / ".schemas" / "fabric"]
    for c in candidates:
        if c and (Path(c) / "pbip").is_dir():
            return Path(c)
    return None


@pytest.fixture(scope="session")
def schema_validator():
    """Return validate(instance) that checks a JSON file against its $schema."""
    jsonschema = pytest.importorskip("jsonschema")
    referencing = pytest.importorskip("referencing")
    base = _schemas_dir()
    if base is None:
        pytest.skip("Microsoft JSON schemas not available (set PBIP_SCHEMAS_DIR)")

    def retrieve(uri: str):
        if not uri.startswith(SCHEMA_PREFIX):
            raise referencing.exceptions.NoSuchResource(uri)
        path = base / uri[len(SCHEMA_PREFIX) :].split("#")[0]
        contents = json.loads(path.read_text(encoding="utf-8"))
        return referencing.Resource.from_contents(contents, default_specification=referencing.jsonschema.DRAFT7)

    registry = referencing.Registry(retrieve=retrieve)

    def validate(instance: dict) -> None:
        schema = retrieve(instance["$schema"]).contents
        cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft7Validator)
        validator = cls(schema, registry=registry)
        errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
        if errors:
            raise AssertionError("\n".join(f"{list(e.path)}: {e.message}" for e in errors[:10]))

    return validate


@pytest.fixture
def example_data(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    shutil.copytree(EXAMPLE_DATA, target)
    return target


@pytest.fixture(autouse=True)
def _allow_test_folders(monkeypatch, tmp_path_factory):
    """The MCP tools only touch PBIP_ALLOWED_ROOTS: allow the pytest temporary folders."""
    monkeypatch.setenv("PBIP_ALLOWED_ROOTS", str(tmp_path_factory.getbasetemp()))
