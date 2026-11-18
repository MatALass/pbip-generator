"""Generate Power BI projects (PBIP: TMDL semantic model + PBIR report) from CSV/Excel files."""

from .builder import render_project, write_project
from .config import ProjectConfig
from .inference import infer_project

__version__ = "0.1.0"
__all__ = ["ProjectConfig", "infer_project", "render_project", "write_project", "__version__"]
