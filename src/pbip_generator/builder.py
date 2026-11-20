"""Assemble every file of a PBIP project and write it to disk."""

from __future__ import annotations

import re
import shutil
import tempfile
import warnings
from pathlib import Path

from . import pbir, tmdl
from .checks import LayoutError, check_pages
from .dictionary import render_dictionary
from .errors import ProjectNameError
from .layout import build_pages
from .model import Page, Project

GITIGNORE = "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n"


def render_project(project: Project, strict: bool = False) -> dict[str, str]:
    """Return {relative path: content} for the whole project folder.

    The report layout is checked first (overlapping visuals, visuals outside the page or too small
    to show their data). Issues are emitted as warnings, or raised as ``LayoutError`` when
    ``strict`` is true.
    """
    pages = project.pages or build_pages(project) or [Page("Page 1")]
    issues = check_pages(pages)
    if issues and strict:
        raise LayoutError(issues)
    for issue in issues:
        warnings.warn(f"Report layout: {issue}", stacklevel=2)
    report_dir = f"{project.name}.Report"
    model_dir = f"{project.name}.SemanticModel"
    files: dict[str, str] = {
        f"{project.name}.pbip": pbir.render_pbip(project),
        ".gitignore": GITIGNORE,
        "DATA_DICTIONARY.md": render_dictionary(project),
        f"{report_dir}/definition.pbir": pbir.render_pbir(project),
        f"{report_dir}/.platform": pbir.render_platform(project, "Report"),
        f"{model_dir}/definition.pbism": pbir.render_pbism(),
        f"{model_dir}/.platform": pbir.render_platform(project, "SemanticModel"),
    }
    for rel, content in pbir.render_report_definition(project, pages).items():
        files[f"{report_dir}/definition/{rel}"] = content
    for rel, content in pbir.render_static_resources(project).items():
        files[f"{report_dir}/StaticResources/{rel}"] = content
    for rel, content in tmdl.render_definition(project).items():
        files[f"{model_dir}/definition/{rel}"] = content
    return files


def write_project(
    project: Project,
    output_dir: Path,
    overwrite: bool = False,
    copy_data: bool = False,
    strict: bool = False,
) -> Path:
    """Write the project to ``output_dir/<name>`` and return that folder.

    The project is written in full in a temporary folder next to it, then swapped in: a failure
    while writing leaves the previous project untouched, and the data copied from the previous
    project's own ``data`` folder is copied before that folder goes away.

    The name must be a plain folder name: it may come from a language model through the MCP
    server, and ``overwrite`` replaces ``output_dir/<name>``.
    """
    check_project_name(project.name)
    files = render_project(project, strict=strict)
    output = Path(output_dir).resolve()
    root = output / project.name
    if root.resolve().parent != output:
        raise ProjectNameError(f"Project name '{project.name}' does not stay inside {output}")
    if root.exists() and not overwrite:
        raise FileExistsError(f"{root} already exists (use --overwrite)")
    output.mkdir(parents=True, exist_ok=True)
    # Same folder as the target, so the final swap is a rename on the same drive. A short name:
    # report files sit deep below it and Windows paths stop at 260 characters.
    staging = Path(tempfile.mkdtemp(prefix=".pbip-", dir=output))
    try:
        for rel, content in files.items():
            path = staging / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            # TMDL and PBIR are text formats; LF endings keep git diffs clean.
            path.write_text(content, encoding="utf-8", newline="\n")
        if copy_data and project.source_dir is not None:
            shutil.copytree(project.source_dir, staging / "data")
        _swap(staging, root)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return root


def _swap(new: Path, root: Path) -> None:
    """Replace ``root`` by ``new``; on failure, ``root`` is put back as it was."""
    if not root.exists():
        new.rename(root)
        return
    old = root.with_name(f"{new.name}-old")
    root.rename(old)  # fails, untouched, if a file of the project is locked
    try:
        new.rename(root)
    except BaseException:
        old.rename(root)
        raise
    shutil.rmtree(old, ignore_errors=True)


# Characters Windows refuses in a file name, plus both path separators.
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def check_project_name(name: str) -> None:
    """A plain folder name: no separator, not '.' or '..', valid on Windows."""
    if not name or name.strip() != name or name in (".", "..") or name.endswith("."):
        raise ProjectNameError(f"Invalid project name '{name}': use a plain name such as 'Ventes2026'")
    if _FORBIDDEN.search(name):
        raise ProjectNameError(f"Invalid project name '{name}': no path separator or any of <>:\"/\\|?*")
    if name.split(".")[0].upper() in _RESERVED:
        raise ProjectNameError(f"Invalid project name '{name}': reserved by Windows")


_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
