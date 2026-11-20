"""Generate Power BI projects (PBIP: TMDL semantic model + PBIR report) from CSV/Excel files."""

from .builder import render_project, write_project
from .checks import LayoutError, LayoutIssue, check_project
from .config import ProjectConfig
from .inference import infer_project

__version__ = "0.1.0"
__all__ = [
    "LayoutError",
    "LayoutIssue",
    "ProjectConfig",
    "check_project",
    "infer_project",
    "render_project",
    "write_project",
    "__version__",
]
