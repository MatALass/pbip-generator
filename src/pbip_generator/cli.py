"""Command line interface.

pbip-generator build DATA_DIR -o OUT [--name NAME] [--config cfg.yaml]
                     [--data-folder "C:\\path\\to\\data\\"] [--copy-data] [--overwrite]
pbip-generator build DATA_DIR -o OUT --spec report.yaml
pbip-generator init-config DATA_DIR [-o config.yaml]
pbip-generator spec-schema [-o schema.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .builder import write_project
from .config import ConfigError, ProjectConfig, dump_inferred
from .inference import infer_project
from .spec import build_project_from_spec, load_spec, spec_json_schema


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pbip-generator",
        description="Generate a ready-to-open Power BI project (PBIP: TMDL + PBIR) from a folder of CSV/Excel files.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="Generate the PBIP project")
    build.add_argument("data_dir", type=Path, help="Folder containing CSV/XLSX files")
    build.add_argument("-o", "--output", type=Path, default=Path("output"))
    build.add_argument("-n", "--name", help="Project name (default: data folder name)")
    build.add_argument("-c", "--config", type=Path, help="YAML config with overrides")
    build.add_argument(
        "-s", "--spec", type=Path, help="Report spec (YAML or JSON): model overrides and pages, replaces --config"
    )
    build.add_argument(
        "--data-folder",
        help="Folder Power BI will read the files from, as seen on the machine that "
        "opens the project (default: absolute path of DATA_DIR)",
    )
    build.add_argument("--copy-data", action="store_true", help="Copy the source files into <project>/data")
    build.add_argument("--overwrite", action="store_true")
    build.add_argument(
        "--strict",
        action="store_true",
        help="Fail instead of warning when visuals overlap, leave the page or are too small",
    )

    init = sub.add_parser("init-config", help="Write the inferred config as editable YAML")
    init.add_argument("data_dir", type=Path)
    init.add_argument("-o", "--output", type=Path, default=Path("pbip-config.yaml"))
    init.add_argument("-n", "--name")

    schema = sub.add_parser("spec-schema", help="Print the JSON schema of the report spec")
    schema.add_argument("-o", "--output", type=Path, help="Write to a file instead of stdout")
    return parser


def _default_name(data_dir: Path) -> str:
    folder = data_dir.resolve()
    name = folder.parent.name if folder.name.lower() == "data" else folder.name
    return name[:1].upper() + name[1:]


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            if args.spec is not None:
                if args.config is not None:
                    raise ConfigError("--spec and --config cannot be used together (the spec holds the overrides)")
                spec = load_spec(args.spec)
                name = args.name or spec.name or _default_name(args.data_dir)
                project = build_project_from_spec(args.data_dir, spec, name, args.data_folder)
            else:
                config = ProjectConfig.load(args.config)
                name = args.name or config.name or _default_name(args.data_dir)
                project = infer_project(args.data_dir, name, args.data_folder, config)
            root = write_project(
                project, args.output, overwrite=args.overwrite, copy_data=args.copy_data, strict=args.strict
            )
            _summary(project, root)
        elif args.command == "spec-schema":
            text = json.dumps(spec_json_schema(), indent=2, ensure_ascii=False) + "\n"
            if args.output is None:
                sys.stdout.write(text)
            else:
                args.output.write_text(text, encoding="utf-8")
                print(f"Schema written to {args.output}")
        else:
            name = args.name or _default_name(args.data_dir)
            project = infer_project(args.data_dir, name)
            args.output.write_text(dump_inferred(project), encoding="utf-8")
            print(f"Config written to {args.output}")
    except (ConfigError, FileNotFoundError, FileExistsError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _summary(project, root: Path) -> None:
    print(f"Project written to {root}")
    for t in project.tables:
        print(f"  {t.role.value:<9} {t.name} ({len(t.columns)} columns, {len(t.measures)} measures)")
    for r in project.relationships:
        flag = "" if r.is_active else " (inactive)"
        print(f"  rel       {r.from_table}[{r.from_column}] -> {r.to_table}[{r.to_column}]{flag}")
    print(f"  DataFolder parameter: {project.data_folder}")
    print(f"Open {root / (project.name + '.pbip')} in Power BI Desktop, then Refresh.")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
