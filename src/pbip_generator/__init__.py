"""Generate Power BI projects (PBIP: TMDL semantic model + PBIR report) from CSV/Excel files."""

from .builder import render_project, write_project
from .checks import LayoutError, LayoutIssue, check_project
from .config import ProjectConfig
from .inference import infer_project
from .spec import ReportSpec, SpecError, build_project_from_spec, load_spec, parse_spec

__version__ = "0.1.0"
__all__ = [
    "LayoutError",
    "LayoutIssue",
    "ProjectConfig",
    "ReportSpec",
    "SpecError",
    "build_project_from_spec",
    "check_project",
    "infer_project",
    "load_spec",
    "parse_spec",
    "render_project",
    "write_project",
    "__version__",
]
