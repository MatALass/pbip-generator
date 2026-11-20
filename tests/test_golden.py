"""Snapshot tests: the files generated for the examples are frozen in tests/golden/.

Any change to the generated TMDL, PBIR or theme shows up as a diff of those files in review.
After an intended change, regenerate them and commit the diff with the change:

    UPDATE_GOLDEN=1 pytest tests/test_golden.py
"""

from __future__ import annotations

import difflib
import os
import shutil
from pathlib import Path

import pytest

from pbip_generator import ProjectConfig, build_project_from_spec, infer_project, load_spec, parse_spec, render_project

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden"
EXAMPLE = ROOT / "examples" / "ventes"
# A fixed DataFolder: the default is the absolute path of the data, different on every machine.
DATA_FOLDER = "C:\\pbip\\Ventes\\data\\"


def _auto() -> dict[str, str]:
    config = ProjectConfig.load(EXAMPLE / "config.yaml")
    return render_project(infer_project(EXAMPLE / "data", "Ventes", DATA_FOLDER, config), strict=True)


def _spec() -> dict[str, str]:
    project = build_project_from_spec(EXAMPLE / "data", load_spec(EXAMPLE / "report.yaml"), "Ventes", DATA_FOLDER)
    return render_project(project, strict=True)


def _spec_dark() -> dict[str, str]:
    raw = load_spec(EXAMPLE / "report.yaml").model_dump(by_alias=True)
    spec = parse_spec({**raw, "theme": {"preset": "dark"}})
    return render_project(build_project_from_spec(EXAMPLE / "data", spec, "Ventes", DATA_FOLDER), strict=True)


CASES = {"ventes-auto": _auto, "ventes-spec": _spec, "ventes-spec-dark": _spec_dark}


@pytest.mark.parametrize("case", sorted(CASES))
def test_output_matches_golden(case):
    files = CASES[case]()
    folder = GOLDEN / case
    if os.environ.get("UPDATE_GOLDEN"):
        shutil.rmtree(folder, ignore_errors=True)
        for rel, content in files.items():
            path = folder / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        pytest.skip(f"golden files of {case} rewritten")
    assert folder.is_dir(), f"no golden files for {case}: run UPDATE_GOLDEN=1 pytest tests/test_golden.py"
    expected = {p.relative_to(folder).as_posix(): p for p in folder.rglob("*") if p.is_file()}
    assert sorted(files) == sorted(expected), "generated files differ from the golden list"
    for rel, content in sorted(files.items()):
        golden = expected[rel].read_text(encoding="utf-8")
        if content != golden:
            diff = "".join(
                difflib.unified_diff(
                    golden.splitlines(keepends=True), content.splitlines(keepends=True), f"golden/{rel}", rel, n=2
                )
            )
            pytest.fail(f"{case}: {rel} changed\n{diff[:4000]}")


def test_generation_is_deterministic():
    assert _spec() == _spec()
