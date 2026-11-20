"""Assemble every file of a PBIP project and write it to disk."""

from __future__ import annotations

import shutil
import warnings
from pathlib import Path

from . import pbir, tmdl
from .checks import LayoutError, check_pages
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
    """Write the project to ``output_dir/<name>`` and return that folder."""
    files = render_project(project, strict=strict)
    root = Path(output_dir) / project.name
    if root.exists():
        if not overwrite:
            raise FileExistsError(f"{root} already exists (use --overwrite)")
        shutil.rmtree(root)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        # TMDL and PBIR are text formats; LF endings keep git diffs clean.
        path.write_text(content, encoding="utf-8", newline="\n")
    if copy_data and project.source_dir is not None:
        shutil.copytree(project.source_dir, root / "data")
    return root
