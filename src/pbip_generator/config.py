"""Optional YAML config to correct or enrich what inference produces.

Example (every key is optional)::

    name: Ventes
    culture: fr-FR
    theme: theme.json             # Power BI theme, path relative to this file
    data_folder: 'C:\\Users\\me\\Projets\\ventes\\data\\'
    date_table: true
    auto_measures: true
    auto_relationships: true
    tables:
      Calendrier:
        role: date                # your own date table, marked as date table
        key: Date                 # its unique date column
      Ventes:
        role: fact                # fact | dimension | date
        types: {CodePostal: string}
        hide: [Commentaire]
        measures:
          - name: Panier moyen
            expression: DIVIDE([Total Montant], [Nb Ventes])
            format: '#,##0.00 €'
            folder: KPI
    relationships:
      add:
        - from: Ventes[ClientID]
          to: Clients[ClientID]
          active: true
      remove:
        - from: Ventes[ProduitID]
          to: Produits[ProduitID]
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import PbipGeneratorError
from .model import DataType, Measure, Project, Relationship, TableRole

_REF = re.compile(r"^\s*(?P<table>.+?)\s*\[(?P<column>.+)\]\s*$")


class ConfigError(PbipGeneratorError, ValueError):
    pass


def _config_errors(method):
    """An unknown table or column in the config is the user's error: report it as such."""

    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except KeyError as exc:
            raise ConfigError(exc.args[0] if exc.args else str(exc)) from exc

    return wrapper


def _parse_ref(text: str) -> tuple[str, str]:
    match = _REF.match(text or "")
    if not match:
        raise ConfigError(f"Invalid column reference '{text}', expected Table[Column]")
    return match["table"].strip("'"), match["column"]


@dataclass
class ProjectConfig:
    name: str | None = None
    culture: str = "fr-FR"
    data_folder: str | None = None
    date_table: bool = True
    auto_measures: bool = True
    auto_relationships: bool = True
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)
    relationships: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    theme: str | None = None
    base_dir: Path | None = field(default=None, repr=False)  # folder of the YAML, for relative paths

    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls, path: Path | None) -> ProjectConfig:
        if path is None:
            return cls()
        try:
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigError("The config root must be a mapping")
        known = set(cls.__dataclass_fields__)
        unknown = set(raw) - (known - {"base_dir"})
        if unknown:
            raise ConfigError(f"Unknown config keys: {sorted(unknown)}")
        return cls(**raw, base_dir=Path(path).resolve().parent)

    # ------------------------------------------------------------------ #
    @_config_errors
    def apply_structure(self, project: Project) -> None:
        """Roles, column types, hidden columns and relationships."""
        for tname, opts in self.tables.items():
            if not project.has_table(tname):
                raise ConfigError(f"Config refers to unknown table '{tname}'")
            table = project.table(tname)
            if "role" in opts:
                try:
                    table.role = TableRole(opts["role"])
                except ValueError as exc:
                    raise ConfigError(f"Invalid role for '{tname}': {opts['role']}") from exc
            for cname, dtype in (opts.get("types") or {}).items():
                col = table.column(cname)
                try:
                    new_type = DataType(dtype)
                except ValueError as exc:
                    raise ConfigError(f"Invalid type '{dtype}' for {tname}[{cname}]") from exc
                if new_type == col.data_type:
                    continue
                col.data_type = new_type
                if col.data_type not in (DataType.INT64, DataType.DOUBLE):
                    col.summarize_by, col.format_string = "none", None
                if col.data_type == DataType.DATETIME:
                    col.is_date_only, col.format_string = True, "dd/mm/yyyy"
            for cname in opts.get("hide") or []:
                table.column(cname).is_hidden = True
            if "key" in opts:
                key = table.column(opts["key"])
                key.is_key = key.is_unique = True
            if table.role == TableRole.DATE and not any(c.is_key for c in table.columns):
                raise ConfigError(f"Date table '{tname}' needs a 'key' column (its unique date column)")

        for item in self.relationships.get("remove") or []:
            ft, fc = _parse_ref(item.get("from"))
            tt, tc = _parse_ref(item.get("to"))
            project.relationships = [
                r
                for r in project.relationships
                if (r.from_table, r.from_column, r.to_table, r.to_column) != (ft, fc, tt, tc)
            ]
        for item in self.relationships.get("add") or []:
            ft, fc = _parse_ref(item.get("from"))
            tt, tc = _parse_ref(item.get("to"))
            project.table(ft).column(fc)  # existence checks
            project.table(tt).column(tc)
            project.relationships.append(Relationship(ft, fc, tt, tc, is_active=bool(item.get("active", True))))
            if project.table(ft).role == TableRole.DIMENSION and "role" not in self.tables.get(ft, {}):
                if not any(r.to_table == ft for r in project.relationships):
                    project.table(ft).role = TableRole.FACT

    def apply_theme(self, project: Project) -> None:
        if not self.theme:
            return
        path = Path(self.theme)
        if not path.is_absolute() and self.base_dir is not None:
            path = self.base_dir / path
        try:
            theme = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"Cannot read theme '{path}': {exc}") from exc
        if not isinstance(theme, dict) or "name" not in theme:
            raise ConfigError(f"Theme '{path}' must be a JSON object with a 'name'")
        project.theme = theme

    @_config_errors
    def apply_measures(self, project: Project) -> None:
        for tname, opts in self.tables.items():
            table = project.table(tname)
            for spec in opts.get("measures") or []:
                if "name" not in spec or "expression" not in spec:
                    raise ConfigError(f"Measure in '{tname}' needs 'name' and 'expression'")
                table.measures = [m for m in table.measures if m.name != spec["name"]]
                table.measures.append(
                    Measure(
                        name=spec["name"],
                        expression=str(spec["expression"]).strip(),
                        format_string=spec.get("format"),
                        display_folder=spec.get("folder", "Personnalisées"),
                        description=spec.get("description"),
                    )
                )


def dump_inferred(project: Project) -> str:
    """YAML describing what was inferred, as a starting point for edits."""
    doc: dict[str, Any] = {
        "name": project.name,
        "culture": project.culture,
        "data_folder": project.data_folder,
        "date_table": project.date_table is not None,
        "tables": {},
        "relationships": {"add": [], "remove": []},
    }
    for t in project.tables:
        if t.role == TableRole.DATE:
            continue
        doc["tables"][t.name] = {
            "role": t.role.value,
            "types": {c.name: c.data_type.value for c in t.columns},
            "measures": [],
        }
    header = (
        "# Configuration inferred by pbip-generator. Edit and pass it back with --config.\n"
        "# Detected relationships (many -> one):\n"
        + "".join(
            f"#   {r.from_table}[{r.from_column}] -> {r.to_table}[{r.to_column}]"
            f"{'' if r.is_active else ' (inactive)'}\n"
            for r in project.relationships
        )
        + "# Auto measures: "
        + ", ".join(m.name for _, m in project.all_measures())
        + "\n"
    )
    return header + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
