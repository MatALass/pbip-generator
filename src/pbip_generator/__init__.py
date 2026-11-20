"""Generate Power BI projects (PBIP: TMDL semantic model + PBIR report) from CSV/Excel files."""

from .builder import render_project, write_project
from .checks import LayoutError, LayoutIssue, check_project
from .config import ConfigError, ProjectConfig
from .errors import AccessError, DataError, PbipGeneratorError, ProjectNameError
from .inference import infer_project
from .spec import ReportSpec, SpecError, build_project_from_spec, load_spec, parse_spec

__version__ = "0.2.0"
__all__ = [
    "AccessError",
    "ConfigError",
    "DataError",
    "LayoutError",
    "LayoutIssue",
    "PbipGeneratorError",
    "ProjectConfig",
    "ProjectNameError",
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
