"""``iris`` command-line interface for IRIS.

The CLI is the only thing the Claude Code agent ever calls. It is the hard
wall between the conversation layer and the computation layer:

    iris config show                         # print loaded configuration
    iris config validate                     # check that referenced files exist
    iris config edit globals plot_backend pyqtgraph
    iris ops list                            # list all operations + parameter schemas
    iris sources list                        # list registered data sources
    iris project new my-analysis
    iris project open my-analysis
    iris project list
    iris session new --label "test-b"
    iris session list
    iris session show <session_dir>
    iris run "mea_trace(861).butter_bandpass.spectrogram"  --session <session_dir>

``mea_trace`` in the DSL refers to the multi-electrode-array hardware data
source and is unrelated to the old CLI name. Run ``iris --help`` for the
full subcommand tree.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from iris import __version__ as IRIS_VERSION
from iris import projects as _projects
from iris.config import (
    DEFAULT_CONFIG_DIR,
    apply_project_overrides,
    edit_yaml,
    load_configs,
    render_summary,
)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 1
    try:
        return int(func(args) or 0)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except Exception as e:  # pragma: no cover - top-level error handler
        print(f"error: {e}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iris",
        description="IRIS: Calcium-Assisted Spike Identity - pipeline CLI.",
    )
    parser.add_argument("--version", action="version", version=f"iris {IRIS_VERSION}")
    parser.add_argument(
        "--config-dir",
        default=DEFAULT_CONFIG_DIR,
        help="Directory containing config.toml (default: %(default)s)",
    )

    sub = parser.add_subparsers(dest="cmd", metavar="<command>")

    # ----- start -----
    p_start = sub.add_parser("start", help="Launch the full IRIS stack (daemon + Express + Vite)")
    p_start.set_defaults(func=cmd_start)

    # ----- reset -----
    p_reset = sub.add_parser(
        "reset", help="Wipe ALL IRIS user data (projects, active pointer, conversations)"
    )
    p_reset.add_argument("--force", action="store_true", help="Skip confirmation prompt")
    p_reset.set_defaults(func=cmd_reset)

    # ----- config -----
    p_config = sub.add_parser("config", help="View or edit configuration")
    sub_config = p_config.add_subparsers(dest="subcmd", metavar="<subcommand>")

    p_config_show = sub_config.add_parser("show", help="Print the loaded configuration")
    p_config_show.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    p_config_show.set_defaults(func=cmd_config_show)

    p_config_validate = sub_config.add_parser(
        "validate", help="Check that referenced files exist and ops dicts are valid"
    )
    p_config_validate.set_defaults(func=cmd_config_validate)

    p_config_edit = sub_config.add_parser("edit", help="Edit a single value in a config file")
    p_config_edit.add_argument("file", choices=("paths", "ops", "globals"))
    p_config_edit.add_argument("key", help="Dotted key path, e.g. butter_bandpass.low_hz")
    p_config_edit.add_argument("value", help="New value (parsed as JSON if possible)")
    p_config_edit.set_defaults(func=cmd_config_edit)

    # ----- ops -----
    p_ops = sub.add_parser("ops", help="Inspect available operations")
    sub_ops = p_ops.add_subparsers(dest="subcmd", metavar="<subcommand>")
    p_ops_list = sub_ops.add_parser("list", help="List all 17 ops with their type signatures")
    p_ops_list.add_argument("--json", action="store_true")
    p_ops_list.set_defaults(func=cmd_ops_list)

    # ----- sources -----
    p_sources = sub.add_parser("sources", help="Inspect registered data sources")
    sub_sources = p_sources.add_subparsers(dest="subcmd", metavar="<subcommand>")
    p_sources_list = sub_sources.add_parser("list", help="List all data source loaders")
    p_sources_list.set_defaults(func=cmd_sources_list)

    # ----- session -----
    p_session = sub.add_parser("session", help="Manage analysis sessions (output directories)")
    sub_session = p_session.add_subparsers(dest="subcmd", metavar="<subcommand>")

    p_sess_new = sub_session.add_parser("new", help="Create a new session output directory")
    p_sess_new.add_argument("--label", default=None, help="Optional human-readable label suffix")
    p_sess_new.set_defaults(func=cmd_session_new)

    p_sess_list = sub_session.add_parser("list", help="List existing sessions")
    p_sess_list.set_defaults(func=cmd_session_list)

    p_sess_show = sub_session.add_parser("show", help="Print a session's manifest.json")
    p_sess_show.add_argument("session", help="Session directory path or basename")
    p_sess_show.set_defaults(func=cmd_session_show)

    # ----- project -----
    p_project = sub.add_parser("project", help="Manage IRIS project workspaces")
    sub_project = p_project.add_subparsers(dest="subcmd", metavar="<subcommand>")

    p_proj_new = sub_project.add_parser("new", help="Create a new project from TEMPLATE")
    p_proj_new.add_argument("name", help="Project name ([a-zA-Z0-9_-]{1,64})")
    p_proj_new.add_argument("--description", default=None, help="Short human-readable description")
    p_proj_new.add_argument(
        "--open", action="store_true", help="Also set the new project as active"
    )
    p_proj_new.set_defaults(func=cmd_project_new)

    p_proj_open = sub_project.add_parser("open", help="Set a project as active")
    p_proj_open.add_argument("name", help="Project name")
    p_proj_open.set_defaults(func=cmd_project_open)

    p_proj_close = sub_project.add_parser("close", help="Clear the active project pointer")
    p_proj_close.set_defaults(func=cmd_project_close)

    p_proj_list = sub_project.add_parser("list", help="List all projects")
    p_proj_list.set_defaults(func=cmd_project_list)

    p_proj_info = sub_project.add_parser("info", help="Show project metadata")
    p_proj_info.add_argument(
        "name", nargs="?", default=None, help="Project name (default: active project)"
    )
    p_proj_info.set_defaults(func=cmd_project_info)

    p_proj_ref = sub_project.add_parser("reference", help="Manage references stored in a project")
    sub_ref = p_proj_ref.add_subparsers(dest="ref_cmd", metavar="<subcmd>")

    p_ref_add = sub_ref.add_parser("add", help="Record a new reference")
    p_ref_add.add_argument("url_or_path", help="URL (for web/claude) or file path (for user)")
    p_ref_add.add_argument(
        "--source",
        required=True,
        choices=("web", "user", "claude"),
        help="Where this reference came from",
    )
    p_ref_add.add_argument("--summary", required=True, help="Short one-paragraph summary")
    p_ref_add.add_argument("--title", default=None, help="Optional display title")
    p_ref_add.add_argument(
        "--tag",
        action="append",
        default=None,
        help="Tag (can be passed multiple times)",
    )
    p_ref_add.add_argument("--project", default=None, help="Project name (default: active)")
    p_ref_add.set_defaults(func=cmd_project_reference_add)

    p_ref_list = sub_ref.add_parser("list", help="List all references in a project")
    p_ref_list.add_argument("--project", default=None, help="Project name (default: active)")
    p_ref_list.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    p_ref_list.set_defaults(func=cmd_project_reference_list)

    p_ref_show = sub_ref.add_parser("show", help="Print the raw contents of a reference stub")
    p_ref_show.add_argument("title_or_path", help="Reference title substring or path")
    p_ref_show.add_argument("--project", default=None, help="Project name (default: active)")
    p_ref_show.set_defaults(func=cmd_project_reference_show)

    p_find_plot = sub_project.add_parser(
        "find-plot",
        help="Find existing plots in a project whose DSL + sources + window match a query",
    )
    p_find_plot.add_argument(
        "dsl", help='DSL expression, e.g. "mea_trace(861).butter_bandpass.spectrogram"'
    )
    p_find_plot.add_argument(
        "--window", default=None, help='Window directive: "full" or "<start_ms>,<end_ms>"'
    )
    p_find_plot.add_argument("--project", default=None, help="Project name (default: active)")
    p_find_plot.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    p_find_plot.set_defaults(func=cmd_project_find_plot)

    # ----- run -----
    p_run = sub.add_parser("run", help="Execute a single DSL expression and save plots")
    p_run.add_argument(
        "dsl", help='DSL expression, e.g. "mea_trace(861).butter_bandpass.spectrogram"'
    )
    p_run.add_argument(
        "--session",
        default=None,
        help="Session directory (created if it does not exist). "
        "If omitted, a new session is created.",
    )
    p_run.add_argument(
        "--label", default=None, help="Label for a new session (with --session omitted)"
    )
    p_run.add_argument(
        "--window",
        default=None,
        help='Window directive: "full" or "<start_ms>,<end_ms>" (overrides [plot].window_ms)',
    )
    p_run.add_argument("--backend", default=None, help="Override [plot].backend for this run")
    p_run.add_argument(
        "--force", action="store_true", help="Bypass the project plot cache and always re-run"
    )
    p_run.set_defaults(func=cmd_run)

    return parser


# ===== command implementations =====


def cmd_start(_args: argparse.Namespace) -> int:
    """Launch the full IRIS stack: Python daemon + Express server + Vite dev server."""
    import subprocess
    import threading

    iris_root = Path(__file__).resolve().parent.parent.parent
    app_dir = iris_root / "iris-app"

    if not app_dir.is_dir():
        print(f"error: iris-app directory not found at {app_dir}", file=sys.stderr)
        return 1

    # Start the Python daemon in a background thread
    daemon_thread = threading.Thread(target=_run_daemon, daemon=True)
    daemon_thread.start()
    print("IRIS daemon starting on :4002")

    # Start the webapp (Express + Vite) via npm
    print("Webapp starting on :4001 (Express) + :4173 (Vite)")
    print()
    try:
        proc = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=str(app_dir),
            shell=(sys.platform == "win32"),
        )
        proc.wait()
        return proc.returncode or 0
    except KeyboardInterrupt:
        print("\nshutting down...")
        return 0


def cmd_reset(args: argparse.Namespace) -> int:
    """Wipe ALL IRIS user data: projects, active pointer, conversations."""
    iris_root = Path(__file__).resolve().parent.parent.parent
    projects_dir = iris_root / "projects"
    iris_dir = iris_root / ".iris"

    # Collect what will be deleted
    targets: list[Path] = []
    if iris_dir.is_dir():
        targets.append(iris_dir)
    if projects_dir.is_dir():
        for child in sorted(projects_dir.iterdir()):
            # Keep TEMPLATE, CLAUDE.md, README.md
            if child.name in ("TEMPLATE", "CLAUDE.md", "README.md"):
                continue
            targets.append(child)

    if not targets:
        print("nothing to reset — no user data found")
        return 0

    print("the following will be PERMANENTLY deleted:")
    for t in targets:
        print(f"  {t}")

    if not getattr(args, "force", False):
        try:
            answer = input("\ntype 'yes' to confirm: ")
        except (KeyboardInterrupt, EOFError):
            print("\naborted")
            return 1
        if answer.strip().lower() != "yes":
            print("aborted")
            return 1

    import shutil

    for t in targets:
        if t.is_dir():
            shutil.rmtree(t)
        else:
            t.unlink()
        print(f"  deleted: {t}")

    print("\nreset complete")
    return 0


def _run_daemon():
    """Run the FastAPI daemon (blocking — meant for a background thread)."""
    import os

    import uvicorn

    from iris.daemon.app import app

    port = int(os.environ.get("IRIS_DAEMON_PORT", "4002"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


def cmd_config_show(args: argparse.Namespace) -> int:
    cfg = load_configs(args.config_dir)
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "paths": cfg.paths,
                    "ops": cfg.ops,
                    "globals": cfg.globals,
                    "missing_paths": cfg.missing_paths,
                    "project_root": str(cfg.project_root),
                },
                indent=2,
            )
        )
    else:
        print(render_summary(cfg))
    return 0


def cmd_config_validate(args: argparse.Namespace) -> int:
    cfg = load_configs(args.config_dir)
    if cfg.missing_paths:
        print("INVALID: missing files:")
        for entry in cfg.missing_paths:
            print(f"  - {entry}")
        return 1
    print(f"OK: {len(cfg.ops)} ops loaded, all referenced files exist.")
    return 0


def cmd_config_edit(args: argparse.Namespace) -> int:
    try:
        value: Any = json.loads(args.value)
    except json.JSONDecodeError:
        value = args.value
    edit_yaml(args.config_dir, args.file, args.key, value)
    print(f"updated {args.file}.{args.key} = {value!r}")
    return 0


def cmd_ops_list(args: argparse.Namespace) -> int:
    cfg = load_configs(args.config_dir)
    from iris.engine import TYPE_TRANSITIONS

    if getattr(args, "json", False):
        out = {}
        for op_name, transitions in TYPE_TRANSITIONS.items():
            out[op_name] = {
                "transitions": {
                    in_type.__name__: out_type.__name__ for in_type, out_type in transitions.items()
                },
                "params": cfg.ops.get(op_name, {}),
            }
        print(json.dumps(out, indent=2))
        return 0

    print(f"{'op':<22}{'transitions':<48}params")
    print("-" * 100)
    for op_name in sorted(TYPE_TRANSITIONS):
        transitions = TYPE_TRANSITIONS[op_name]
        if transitions:
            tr = "  ".join(
                f"{in_t.__name__}->{out_t.__name__}" for in_t, out_t in transitions.items()
            )
        else:
            tr = "(function-op, validated separately)"
        params = cfg.ops.get(op_name, {})
        param_str = ", ".join(f"{k}={v}" for k, v in params.items())[:60]
        print(f"{op_name:<22}{tr:<48}{param_str}")
    return 0


def cmd_sources_list(args: argparse.Namespace) -> int:
    from iris.engine import create_registry

    _registry, sources = create_registry()
    print("Registered source loaders:")
    for name, loader in sources.items():
        print(f"  {name:<15} → {loader.__module__}.{loader.__name__}")
    return 0


def cmd_session_new(args: argparse.Namespace) -> int:
    from iris.plot_sessions import new_session

    cfg = load_configs(args.config_dir)
    sd = new_session(label=args.label, output_root=cfg.paths["output_dir"])
    print(sd)
    return 0


def cmd_session_list(args: argparse.Namespace) -> int:
    from iris.plot_sessions import list_sessions

    cfg = load_configs(args.config_dir)
    sessions = list_sessions(cfg.paths["output_dir"])
    if not sessions:
        print(f"(no sessions found in {cfg.paths['output_dir']})")
        return 0
    for s in sessions:
        plots = sorted(s.glob("plot_*.png")) + sorted(s.glob("plot_*.pdf"))
        print(f"{s.name:<55}  {len(plots)} plot(s)")
    return 0


def cmd_session_show(args: argparse.Namespace) -> int:
    cfg = load_configs(args.config_dir)
    sd = Path(args.session)
    if not sd.is_absolute():
        sd = Path(cfg.paths["output_dir"]) / sd
    if not sd.is_dir():
        print(f"error: session not found: {sd}", file=sys.stderr)
        return 1
    manifest = sd / "manifest.json"
    if not manifest.is_file():
        print(f"error: manifest.json not found in {sd}", file=sys.stderr)
        return 1
    print(manifest.read_text(encoding="utf-8"))
    return 0


def _parse_window_arg(window_arg: str | None) -> str | list | None:
    """Parse the --window CLI argument into a directive the cache can match.

    Returns:
        "full"  — for ``--window full``
        [s, e]  — for ``--window s,e`` (floats)
        None    — for no --window argument (caller inherits from globals.yaml)
    """
    if window_arg is None:
        return None
    if window_arg == "full":
        return "full"
    try:
        start, end = (float(x.strip()) for x in window_arg.split(","))
    except ValueError:
        raise
    return [start, end]


def _effective_window(
    args_window: str | None,
    globals_cfg: dict,
) -> str | list | None:
    """Resolve the window directive the current run will use.

    --window arg wins, then globals.yaml ``window_ms``, then None (which the
    engine treats as "full"). Returns the same value space as
    _parse_window_arg.
    """
    if args_window is not None:
        return _parse_window_arg(args_window)
    g = globals_cfg.get("window_ms")
    if g in (None, "full"):
        return "full"
    if isinstance(g, (list, tuple)) and len(g) == 2:
        return [float(g[0]), float(g[1])]
    return g


def cmd_run(args: argparse.Namespace) -> int:
    from iris.engine import (
        create_registry,
        get_recording_duration_ms,
        run_pipeline,
    )
    from iris.plot_sessions import new_session, write_manifest

    cfg = load_configs(args.config_dir)
    if cfg.missing_paths:
        print("ERROR: missing input files; aborting:", file=sys.stderr)
        for entry in cfg.missing_paths:
            print(f"  - {entry}", file=sys.stderr)
        return 1

    # An active project is required for all runs.
    project_dir = _projects.resolve_active_project()
    if project_dir is None:
        print("ERROR: no active project. Create or open one first:", file=sys.stderr)
        print("  iris project new <name> --open", file=sys.stderr)
        print("  iris project open <name>", file=sys.stderr)
        return 1
    cfg = apply_project_overrides(cfg, project_dir)
    print(f"project: {project_dir.name}")

    # ---- PLOT-LEVEL CACHE CHECK -------------------------------------
    # Before creating a new session or calling run_pipeline, see if an
    # identical plot already exists in the active project's output.
    # "Identical" means: same DSL string, same source file fingerprints
    # (mtime+size), and the same window directive (with the caveat that
    # "full" windows match any prior sidecar with matching sources —
    # see projects.find_cached_plots for details).
    if not getattr(args, "force", False):
        try:
            effective_window = _effective_window(args.window, cfg.globals)
        except ValueError:
            print(
                f"error: invalid --window {args.window!r}; expected 'full' or 'start,end'",
                file=sys.stderr,
            )
            return 1
        cached = _projects.find_cached_plots(
            project_dir,
            dsl=args.dsl,
            paths_cfg=cfg.paths,
            window_ms=effective_window,
        )
        if cached:
            hit = cached[0]
            print("cached: identical plot already exists in this project")
            print(f"  plot:    {hit.plot_path}")
            print(f"  sidecar: {hit.sidecar_path}")
            print(f"  session: {hit.session_dir.name}")
            if hit.window_ms is not None:
                print(f"  window:  {list(hit.window_ms)} (from sidecar)")
            print(f"  rendered: {hit.timestamp}")
            print()
            print("pass --force to re-run and create a new version.")
            return 0

    backend = args.backend or cfg.globals.get("plot_backend", "matplotlib")

    if args.session:
        session_dir = Path(args.session)
        if not session_dir.is_absolute():
            session_dir = Path(cfg.paths["output_dir"]) / session_dir
        session_dir.mkdir(parents=True, exist_ok=True)
    else:
        session_dir = new_session(label=args.label, output_root=cfg.paths["output_dir"])
        print(f"created session: {session_dir}")

    paths_for_run = dict(cfg.paths)
    paths_for_run["output_dir"] = str(session_dir)

    globals_for_run = dict(cfg.globals)
    globals_for_run["plot_backend"] = backend
    globals_for_run["save_plots"] = True
    if args.window:
        if args.window == "full":
            globals_for_run["window_ms"] = "full"
        else:
            try:
                start, end = (float(x.strip()) for x in args.window.split(","))
            except ValueError:
                print(
                    f"error: invalid --window {args.window!r}; expected 'full' or 'start,end'",
                    file=sys.stderr,
                )
                return 1
            globals_for_run["window_ms"] = [start, end]

    pipeline_cfg: list = [args.dsl]
    if "window_ms" in globals_for_run:
        pass  # run_pipeline injects it from globals_cfg

    registry, source_loaders = create_registry(plot_backend=backend)

    write_manifest(
        session_dir,
        ctx=_StubCtx(),
        paths_cfg=paths_for_run,
        ops_cfg=cfg.ops,
        globals_cfg=globals_for_run,
    )

    print(f"running: {args.dsl}")
    print(f"backend: {backend}")
    print(f"session: {session_dir}")
    run_pipeline(
        paths_cfg=paths_for_run,
        ops_cfg=cfg.ops,
        pipeline_cfg=pipeline_cfg,
        registry=registry,
        source_loaders=source_loaders,
        globals_cfg=globals_for_run,
        get_recording_duration_ms=get_recording_duration_ms,
    )

    plots = sorted(session_dir.glob("*.png")) + sorted(session_dir.glob("*.pdf"))
    if plots:
        print()
        print("Plots saved:")
        for p in plots:
            print(f"  {p}")
    return 0


# ===== project commands =====


def cmd_project_new(args: argparse.Namespace) -> int:
    path = _projects.create_project(args.name, description=args.description)
    print(f"created project: {path}")
    if getattr(args, "open", False):
        _projects.open_project(args.name)
        print(f"active project: {args.name}")
    return 0


def cmd_project_open(args: argparse.Namespace) -> int:
    path = _projects.open_project(args.name)
    print(f"active project: {args.name}  ({path})")
    return 0


def cmd_project_close(args: argparse.Namespace) -> int:
    _projects.close_project()
    print("no active project")
    return 0


def cmd_project_list(args: argparse.Namespace) -> int:
    infos = _projects.list_projects()
    if not infos:
        print(f"(no projects in {_projects.project_root()})")
        return 0
    active = _projects.resolve_active_project()
    active_name = active.name if active is not None else None
    print(f"{'':<2}{'name':<32}{'refs':<6}{'plots':<7}{'description'}")
    print("-" * 90)
    for info in infos:
        marker = "* " if info.name == active_name else "  "
        desc = info.description or ""
        if len(desc) > 40:
            desc = desc[:37] + "..."
        print(f"{marker}{info.name:<32}{info.n_references:<6}{info.n_outputs:<7}{desc}")
    return 0


def cmd_project_info(args: argparse.Namespace) -> int:
    name = args.name
    if name is None:
        active = _projects.resolve_active_project()
        if active is None:
            print(
                "no active project; pass a project name or `iris project open <name>`",
                file=sys.stderr,
            )
            return 1
        name = active.name
    path = _projects.project_root() / name
    if not path.is_dir():
        print(f"error: project not found: {path}", file=sys.stderr)
        return 1
    cfg = _projects.get_project_config(name)
    info = _projects._describe_project(path)
    print(f"name:         {info.name}")
    print(f"path:         {info.path}")
    print(f"created_at:   {info.created_at or '(unset)'}")
    print(f"description:  {info.description or '(none)'}")
    print(f"references:   {info.n_references}")
    print(f"plot files:   {info.n_outputs}")
    if cfg.get("agent_notes"):
        print(f"agent notes:  {cfg['agent_notes']}")
    return 0


def _resolve_project_arg(name: str | None) -> Path | None:
    """Resolve an explicit --project arg or fall back to the active project."""
    if name is not None:
        path = _projects.project_root() / name
        if not path.is_dir():
            print(f"error: project not found: {path}", file=sys.stderr)
            return None
        return path
    active = _projects.resolve_active_project()
    if active is None:
        print(
            "no active project; pass --project <name> or `iris project open <name>`",
            file=sys.stderr,
        )
        return None
    return active


def cmd_project_reference_add(args: argparse.Namespace) -> int:
    path = _resolve_project_arg(args.project)
    if path is None:
        return 1
    ref_path = _projects.add_reference(
        path,
        url_or_path=args.url_or_path,
        source=args.source,
        summary=args.summary,
        tags=args.tag,
        title=args.title,
    )
    print(f"{path.name}: added [{args.source}] {ref_path}")
    return 0


def cmd_project_reference_list(args: argparse.Namespace) -> int:
    path = _resolve_project_arg(args.project)
    if path is None:
        return 1
    refs = _projects.list_references(path)
    if getattr(args, "json", False):
        print(json.dumps(refs, indent=2))
        return 0
    if not refs:
        print(f"(no references in {path})")
        return 0
    print(f"{'source':<8}{'title':<40}{'tags':<20}summary")
    print("-" * 100)
    for r in refs:
        title = (r.get("title") or "")[:38]
        tags = ",".join(r.get("tags") or [])[:18]
        summary = (r.get("summary") or "")[:40]
        print(f"{r.get('source', ''):<8}{title:<40}{tags:<20}{summary}")
    return 0


def cmd_project_find_plot(args: argparse.Namespace) -> int:
    path = _resolve_project_arg(args.project)
    if path is None:
        return 1
    cfg = load_configs(args.config_dir)
    # apply project overrides so paths_cfg reflects the project's view
    cfg = apply_project_overrides(cfg, path)
    try:
        effective_window = _effective_window(args.window, cfg.globals)
    except ValueError:
        print(
            f"error: invalid --window {args.window!r}; expected 'full' or 'start,end'",
            file=sys.stderr,
        )
        return 1
    matches = _projects.find_cached_plots(
        path,
        dsl=args.dsl,
        paths_cfg=cfg.paths,
        window_ms=effective_window,
    )
    if getattr(args, "json", False):
        print(
            json.dumps(
                [
                    {
                        "plot": str(m.plot_path),
                        "sidecar": str(m.sidecar_path),
                        "session": m.session_dir.name,
                        "dsl": m.dsl,
                        "window_ms": list(m.window_ms) if m.window_ms is not None else None,
                        "timestamp": m.timestamp,
                    }
                    for m in matches
                ],
                indent=2,
            )
        )
        return 0
    if not matches:
        print(f"no cached plots in {path.name} match {args.dsl!r}")
        return 0
    print(f"{len(matches)} cached plot(s) match in {path.name}:")
    for m in matches:
        window_str = str(list(m.window_ms)) if m.window_ms is not None else "(none)"
        print(f"  {m.plot_path}")
        print(f"    session:   {m.session_dir.name}")
        print(f"    window:    {window_str}")
        print(f"    rendered:  {m.timestamp}")
    return 0


def cmd_project_reference_show(args: argparse.Namespace) -> int:
    path = _resolve_project_arg(args.project)
    if path is None:
        return 1
    target = Path(args.title_or_path)
    # If a direct path was given and exists, read it
    if target.is_file():
        print(target.read_text(encoding="utf-8"))
        return 0
    # Otherwise, search refs by title or filename substring (case-insensitive)
    needle = args.title_or_path.lower()
    matches: list[dict] = []
    for r in _projects.list_references(path):
        hay = f"{r.get('title', '')} {Path(r['path']).name}".lower()
        if needle in hay:
            matches.append(r)
    if not matches:
        print(f"error: no reference matching {args.title_or_path!r}", file=sys.stderr)
        return 1
    if len(matches) > 1:
        print(f"error: {args.title_or_path!r} matches multiple references:", file=sys.stderr)
        for m in matches:
            print(f"  - {m['path']}", file=sys.stderr)
        return 1
    ref_path = Path(matches[0]["path"])
    if not ref_path.is_file():
        print(f"error: reference file missing: {ref_path}", file=sys.stderr)
        return 1
    print(ref_path.read_text(encoding="utf-8"))
    return 0


class _StubCtx:
    """Minimal stand-in so write_manifest doesn't need a full PipelineContext."""

    window_ms = (0.0, 0.0)


if __name__ == "__main__":
    sys.exit(main())
