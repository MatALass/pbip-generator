"""Check a ReportSpec against the inferred model, before any file is written.

Each issue says where it is and what is available instead, so that whoever wrote the spec (often
a language model) can fix it in one pass.
"""

from __future__ import annotations

import re
from difflib import get_close_matches

from .layout import CHART_MAX_CATEGORIES
from .model import FieldRef, Project
from .spec import CHART_TYPES, TEMPLATE_SLOTS, ReportSpec, VisualSpec

_REF = re.compile(r"^\s*(?:'?(?P<table>[^'\[\]]+?)'?)?\s*\[(?P<name>[^\[\]]+)\]\s*$")
# DAX: strings and comments are removed before references are looked up.
_DAX_NOISE = re.compile(r'"(?:[^"]|"")*"|//[^\n]*|--[^\n]*|/\*.*?\*/', re.S)
_DAX_QUALIFIED = re.compile(r"(?:'((?:[^']|'')+)'|([^\W\d][\w]*))\[([^\]]+)\]")
_DAX_BARE = re.compile(r"(?<![\w'\]])\[([^\]]+)\]")


def _hint(name: str, candidates: list[str], label: str) -> str:
    close = get_close_matches(name, candidates, n=3, cutoff=0.5)
    if close:
        return f"did you mean {', '.join(close)}?"
    shown = ", ".join(candidates[:15]) + (", ..." if len(candidates) > 15 else "")
    return f"{label}: {shown or 'none'}"


def _measure_names(project: Project) -> list[str]:
    return [m.name for _, m in project.all_measures()]


def resolve(project: Project, text: str) -> tuple[FieldRef | None, str | None]:
    """``Table[Column]``, ``Table[Measure]`` or ``[Measure]`` -> (reference, None) or (None, error)."""
    match = _REF.match(text or "")
    if not match:
        return None, f"'{text}' is not a field reference, expected 'Table[Column]' or '[Measure]'"
    tname, name = match["table"], match["name"].strip()
    if tname is None:
        for t, m in project.all_measures():
            if m.name == name:
                return FieldRef(t.name, m.name, is_measure=True), None
        return None, f"unknown measure [{name}], {_hint(name, _measure_names(project), 'measures')}"
    tname = tname.strip()
    if not project.has_table(tname):
        return None, f"unknown table '{tname}', {_hint(tname, [t.name for t in project.tables], 'tables')}"
    table = project.table(tname)
    if any(m.name == name for m in table.measures):
        return FieldRef(tname, name, is_measure=True), None
    if table.has_column(name):
        return FieldRef(tname, name), None
    names = [c.name for c in table.columns if not c.is_hidden] + [m.name for m in table.measures]
    return None, f"'{tname}' has no column or measure '{name}', {_hint(name, names, 'available')}"


def _check_dax(project: Project, expression: str) -> list[str]:
    code = _DAX_NOISE.sub("", expression)
    errors = []
    for quoted, plain, name in _DAX_QUALIFIED.findall(code):
        tname = quoted.replace("''", "'") if quoted else plain
        if project.has_table(tname):
            table = project.table(tname)
            if not table.has_column(name) and not any(m.name == name for m in table.measures):
                errors.append(f"{tname}[{name}] does not exist")
        elif quoted:  # an unquoted word before '[' may be a variable or a function, not a table
            errors.append(f"unknown table '{tname}'")
    known = set(_measure_names(project)) | {c.name for t in project.tables for c in t.columns}
    for name in _DAX_BARE.findall(code):
        if name not in known:
            hint = _hint(name, _measure_names(project), "measures")
            errors.append(f"[{name}] is neither a measure nor a column, {hint}")
    return errors


def _check_measures(spec: ReportSpec, project: Project) -> list[str]:
    issues = []
    seen: dict[str, str] = {}
    for t, m in project.all_measures():
        if m.name in seen:
            issues.append(f"measure '{m.name}' is in both '{seen[m.name]}' and '{t.name}', names must be unique")
        seen[m.name] = t.name
        if t.has_column(m.name):
            issues.append(f"measure '{m.name}' has the name of a column of '{t.name}'")
    for m in spec.measures:
        if not project.has_table(m.table):
            continue  # reported by the config step
        issues += [f"measure '{m.name}': {e}" for e in _check_dax(project, m.expression)]
    return issues


def _field(project: Project, where: str, text: str, kind: str | None = None) -> tuple[FieldRef | None, list[str]]:
    """Resolve ``text``; ``kind`` 'measure' or 'column' restricts what is accepted."""
    ref, error = resolve(project, text)
    if ref is None:
        return None, [f"{where}: {error}"]
    if kind == "measure" and not ref.is_measure:
        return ref, [f"{where}: '{text}' is a column, a measure is expected here (add one in 'measures')"]
    if kind == "column" and ref.is_measure:
        return ref, [f"{where}: '{text}' is a measure, a column is expected here"]
    if not ref.is_measure and project.table(ref.table).column(ref.name).is_hidden:
        return ref, [f"{where}: '{text}' is a hidden technical column, use a readable column of the dimension"]
    return ref, []


def _check_visual(project: Project, where: str, v: VisualSpec) -> list[str]:
    issues: list[str] = []
    if v.type == "textbox":
        if not v.text:
            issues.append(f"{where}: a textbox needs 'text'")
        if v.category or v.values:
            issues.append(f"{where}: a textbox takes no field")
        return issues
    if not v.title:
        issues.append(f"{where}: a {v.type} needs a 'title'")
    if not v.values:
        issues.append(f"{where}: a {v.type} needs at least one entry in 'values'")
    fields: list[str] = list(v.values)
    if v.type in CHART_TYPES:
        if not v.category:
            issues.append(f"{where}: a {v.type} needs a 'category' column")
        else:
            fields.append(v.category)
            cat, errors = _field(project, f"{where}.category", v.category, "column")
            issues += errors
            limit = CHART_MAX_CATEGORIES.get(v.type)
            if cat is not None and not errors and limit is not None:
                count = project.table(cat.table).column(cat.name).distinct_count
                if count > limit:
                    issues.append(
                        f"{where}: '{v.category}' has {count} values, a {v.type} stays readable up to {limit} "
                        "(use a clusteredBarChart, a coarser column or a table)"
                    )
        if v.type == "donutChart" and len(v.values) > 1:
            issues.append(f"{where}: a donutChart shows a single measure")
    elif v.category:
        issues.append(f"{where}: a {v.type} takes no 'category', put every field in 'values'")
    if v.type == "card" and len(v.values) > 1:
        issues.append(f"{where}: a card shows a single measure")
    kind = None if v.type == "tableEx" else "measure"
    for i, text in enumerate(v.values):
        issues += _field(project, f"{where}.values[{i}]", text, kind)[1]
    if v.sort_by is not None and v.sort_by not in fields:
        issues.append(f"{where}: sort_by '{v.sort_by}' must be one of the visual's fields")
    return issues


def validate_spec(spec: ReportSpec, project: Project) -> list[str]:
    """Every issue of the spec once applied to ``project``; empty when the report can be built."""
    issues = _check_measures(spec, project)
    names = [p.name for p in spec.pages]
    for name in sorted({n for n in names if names.count(n) > 1}):
        issues.append(f"several pages are named '{name}'")
    for p, page in enumerate(spec.pages):
        where = f"pages[{p}] '{page.name}'"
        for i, text in enumerate(page.slicers):
            issues += _field(project, f"{where}.slicers[{i}]", text, "column")[1]
        if page.template == "table":
            if page.kpis:
                issues.append(f"{where}: template 'table' has no KPI row, use 'kpis_table' to keep the KPIs")
        elif not page.kpis:
            issues.append(f"{where}: template '{page.template}' needs 1 to 4 'kpis'")
        for i, text in enumerate(page.kpis):
            issues += _field(project, f"{where}.kpis[{i}]", text, "measure")[1]
        expected = TEMPLATE_SLOTS[page.template]
        if len(page.visuals) != expected:
            fits = [t for t, n in TEMPLATE_SLOTS.items() if n == len(page.visuals)]
            hint = f", templates with {len(page.visuals)}: {', '.join(fits)}" if fits else ""
            got = len(page.visuals)
            issues.append(f"{where}: template '{page.template}' holds {expected} visual(s), got {got}{hint}")
        for i, visual in enumerate(page.visuals):
            issues += _check_visual(project, f"{where}.visuals[{i}]", visual)
    return issues
