"""Errors caused by the input (data, config, spec, project name), as opposed to bugs.

The CLI and the MCP server report these as plain messages. Any other exception is a bug in
pbip-generator and keeps its traceback.
"""

from __future__ import annotations


class PbipGeneratorError(Exception):
    """Base of every error the user (or the model writing a spec) can fix."""


class DataError(PbipGeneratorError, ValueError):
    """A source file cannot be read, or two sources clash."""


class ProjectNameError(PbipGeneratorError, ValueError):
    """The project name is not a plain folder name."""


class AccessError(PbipGeneratorError, PermissionError):
    """A path outside the folders the MCP server is allowed to use."""
