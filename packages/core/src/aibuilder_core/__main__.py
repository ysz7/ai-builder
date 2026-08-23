"""Entry point.

With no arguments this is the **sidecar**: NDJSON requests on stdin, NDJSON responses on
stdout. That is how Tauri spawns it, so the argument-free path must never change meaning.

    echo '{"id":1,"method":"ping"}' | uv run python -m aibuilder_core

With a subcommand it is a small CLI, used by CI and by hand:

    uv run python -m aibuilder_core strip <project> <destination>
    uv run python -m aibuilder_core graph <project>
    uv run python -m aibuilder_core check <project> [--observe]
    uv run python -m aibuilder_core snapshot <project>
    uv run python -m aibuilder_core status <project>
    uv run python -m aibuilder_core set-knob <project> <node> <knob> <value>
    uv run python -m aibuilder_core repairs <project>
    uv run python -m aibuilder_core repair <project> <code> <target> <resolution>
    uv run python -m aibuilder_core blueprints
    uv run python -m aibuilder_core brief <project> [--request TEXT] [--blueprint ID]
    uv run python -m aibuilder_core record <project> --source chat|blueprint [--observe]
    uv run python -m aibuilder_core failures <project>
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import TextIO

from aibuilder_core.api import (
    agent_blueprints,
    agent_brief,
    agent_failures,
    agent_record,
    repair_divergence,
    repairs_available,
    snapshot_status,
    take_project_snapshot,
    write_knob,
)
from aibuilder_core.catalog import CATALOG_ENV
from aibuilder_core.gate import check_graph, summarize
from aibuilder_core.handlers import dispatch
from aibuilder_core.observe import run_observations
from aibuilder_core.parser import parse_project
from aibuilder_core.protocol import (
    ProtocolError,
    decode_request,
    encode_error,
    encode_result,
)
from aibuilder_core.strip import strip_project
from aibuilder_core.verdict import Observation


def log(message: str) -> None:
    """stderr only. stdout is the wire; a stray print there corrupts the stream."""
    print(f"[core] {message}", file=sys.stderr, flush=True)


def handle_line(line: str) -> str | None:
    """Turn one request line into one response line. Never raises."""
    line = line.strip()
    if not line:
        return None

    try:
        request = decode_request(line)
    except ProtocolError as exc:
        return encode_error(exc.request_id, exc.code, exc.message)

    log(f"-> {request.method} (id={request.id!r})")

    try:
        return encode_result(request.id, dispatch(request.method, request.params, request.id))
    except ProtocolError as exc:
        return encode_error(request.id, exc.code, exc.message)
    except Exception as exc:  # a handler bug must not take the core down
        log(f"handler {request.method!r} raised: {exc!r}")
        return encode_error(request.id, "handler_error", f"{type(exc).__name__}: {exc}")


def serve(stdin: TextIO, stdout: TextIO) -> None:
    for line in stdin:
        response = handle_line(line)
        if response is None:
            continue
        stdout.write(response + "\n")
        stdout.flush()


def serve_forever() -> int:
    log("ready")
    with contextlib.suppress(KeyboardInterrupt):
        serve(sys.stdin, sys.stdout)
    log("stdin closed, exiting")
    return 0


def run_strip(project: Path, destination: Path) -> int:
    """Write a markup-free copy and report what came off (invariant I-2)."""
    report = strip_project(project, destination)
    print(
        f"stripped {report.files_rewritten}/{report.files_copied} file(s), "
        f"removed {len(report.manifests_removed)} group manifest(s) -> {destination}"
    )
    return 0


def run_graph(project: Path) -> int:
    """Print the graph IR the parser reads out of a project.

    The same data the UI will be handed, dumped where a human can read it -- which is how
    a wrong graph gets diagnosed without a running app in the way.
    """
    print(json.dumps(parse_project(project).to_dict(), indent=2))
    return 0


def run_check(project: Path, observe: bool) -> int:
    """Run the gate and print its diagnostics, addressed.

    Always exits 0 in soft mode: a violation is a badge and a repair offer, not a refusal
    (§7). Hard mode is what a caller uses when it wants a failing exit code.
    """
    graph = parse_project(project)

    observations: dict[str, Observation] = {}
    skipped: dict[str, str] = {}
    if observe:
        run = run_observations(graph, project)
        observations, skipped = run.observations, run.skipped

    result = check_graph(graph, observations=observations)

    for diagnostic in sorted(
        result.diagnostics, key=lambda d: (d.location.file, d.location.start_line)
    ):
        print(f"{diagnostic.severity}: {diagnostic.address}")
        print(f"  {diagnostic.code} ({diagnostic.rule}) -- {diagnostic.message}")
        print(f"  repair: {diagnostic.repair}")

    for node, observation in sorted(observations.items()):
        mark = "pass" if observation.passed else "FAIL"
        print(f"{mark}: {node} -- {observation.check}: {observation.detail}")
    for node, reason in sorted(skipped.items()):
        print(f"unproven: {node} -- {reason}")

    print(summarize(result))
    if observe:
        # The unreached band, stated as a number (Q7). A node no run entered is not a
        # failure and not a pass; it is the dark node in the editor, and the only way to
        # decide whether it needs an authored example is to see how many there are.
        print(f"{len(skipped)} node(s) reached by no run")
    return 0 if result.accepted else 1


def run_snapshot(project: Path) -> int:
    """Make the current outline the reference for future reconciliation."""
    result = take_project_snapshot(project)
    if not result["taken"]:
        print(f"refused: {result['refused']}")
        return 1
    print(f"reference written to {result['path']}")
    return 0


def run_status(project: Path) -> int:
    """What no longer matches the reference -- `git status`, for the graph (§8)."""
    result = snapshot_status(project)
    if not result["has_reference"]:
        print("no reference yet; run `snapshot` on a project that passes the gates")
        return 0

    divergences = result["divergences"]
    for divergence in divergences:
        location = divergence["location"]
        address = f"{location['file']}:{location['start_line']} {location['object']}"
        print(f"{divergence['fault']}: {address}")
        print(f"  {divergence['code']} ({divergence['rule']}) -- {divergence['message']}")
        print(f"  options: {', '.join(divergence['resolutions'])}")

    print(f"{len(divergences)} divergence(s) from the reference")
    return 0


def run_set_knob(project: Path, node: str, knob: str, raw: str) -> int:
    """Write a knob from the command line.

    The value is read as JSON, falling back to a plain string: `50` is an int, `true` is a
    boolean, and `debug` is the word rather than a syntax error.
    """
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw

    result = write_knob(project, node, knob, value)
    if not result["written"]:
        print(f"refused: {result['refused']}")
        for diagnostic in result["diagnostics"]:
            print(f"  {diagnostic['code']} -- {diagnostic['message']}")
        return 1

    print(f"{node}.{knob} = {value!r} written to {result['file']}")
    return 0


def run_repairs(project: Path) -> int:
    """Show every divergence with the request an agent could act on."""
    repairs = repairs_available(project)["repairs"]
    for repair in repairs:
        print(repair["request"])
        print(f"  offered: {', '.join(repair['resolutions'])}")
        if repair["mechanical"]:
            print(f"  the toolchain can do: {', '.join(repair['mechanical'])}")
        print()

    print(f"{len(repairs)} divergence(s)")
    return 0


def run_repair(project: Path, code: str, target: str, resolution: str) -> int:
    result = repair_divergence(project, code, target, resolution)
    if result["refused"]:
        print(f"refused: {result['refused']}")
        for node in result["unproven"]:
            print(f"  still failing its observable check: {node}")
        for diagnostic in result["diagnostics"]:
            print(f"  {diagnostic['code']} -- {diagnostic['message']}")
        return 1

    print(f"{code} on {target}: {resolution} applied; reference updated")
    return 0


def run_blueprints(catalog: Path | None) -> int:
    """List what input B can be given."""
    result = agent_blueprints(catalog)
    if result["catalog"] is None:
        print(
            f"no blueprint catalog found; point at one with the {CATALOG_ENV} environment variable"
        )
        return 1

    for blueprint in result["blueprints"]:
        print(f"{blueprint['id']}  ({blueprint['section']})")
        if blueprint["title"]:
            print(f"  {blueprint['title']}")
    print(f"{len(result['blueprints'])} blueprint(s) in {result['catalog']}")
    return 0


def run_brief(
    project: Path, request: str | None, blueprint: str | None, catalog: Path | None
) -> int:
    """Print the brief the agent would be handed, prompt included.

    Printed rather than sent: the brief is the whole of this phase's output, and a human
    has to be able to read exactly what the agent was told.
    """
    result = agent_brief(project, request, blueprint, catalog)
    if result["refused"]:
        print(f"refused: {result['refused']}")
        return 1

    brief = result["brief"]
    print(brief["system_prompt"])
    print("\n---\n")
    print(brief["instructions"])
    return 0


def run_record(
    project: Path, source: str, request: str, blueprint: str | None, observe: bool
) -> int:
    """Gate a generation and write what it got wrong into the log."""
    entry = agent_record(project, source, request, blueprint, observe)["entry"]
    for diagnostic in entry["diagnostics"]:
        print(f"{diagnostic['severity']}: {diagnostic['code']} at {diagnostic['address']}")
    # Soft mode flags rather than refuses (§7), so "accepted" is true of every run here;
    # what is worth printing is what was flagged.
    print(f"recorded: {len(entry['diagnostics'])} diagnostic(s), flagged not refused")
    return 0


def run_failures(project: Path) -> int:
    """The tally the soft gate exists to collect."""
    result = agent_failures(project)
    for code in result["codes"]:
        print(f"{code['count']}x {code['code']} ({code['rule']})")
        for address in code["addresses"]:
            print(f"    {address}")
    print(f"{result['generations']} generation(s) recorded, {result['clean']} without errors")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aibuilder-core", description=__doc__)
    sub = parser.add_subparsers(dest="command")

    strip_cmd = sub.add_parser(
        "strip",
        help="write a copy of a project with the bp markup layer removed",
    )
    strip_cmd.add_argument("project", type=Path)
    strip_cmd.add_argument("destination", type=Path)

    graph_cmd = sub.add_parser("graph", help="print the graph IR parsed from a project")
    graph_cmd.add_argument("project", type=Path)

    check_cmd = sub.add_parser("check", help="run the gate and print diagnostics")
    check_cmd.add_argument("project", type=Path)
    check_cmd.add_argument(
        "--observe",
        action="store_true",
        help="also run the observable checks -- this imports and runs the project",
    )

    snapshot_cmd = sub.add_parser("snapshot", help="record the current outline as the reference")
    snapshot_cmd.add_argument("project", type=Path)

    status_cmd = sub.add_parser("status", help="show what diverged from the reference")
    status_cmd.add_argument("project", type=Path)

    knob_cmd = sub.add_parser("set-knob", help="write a knob's value into the code")
    knob_cmd.add_argument("project", type=Path)
    knob_cmd.add_argument("node")
    knob_cmd.add_argument("knob")
    knob_cmd.add_argument("value")

    repairs_cmd = sub.add_parser("repairs", help="list divergences and how they can be resolved")
    repairs_cmd.add_argument("project", type=Path)

    repair_cmd = sub.add_parser("repair", help="resolve one divergence")
    repair_cmd.add_argument("project", type=Path)
    repair_cmd.add_argument("code")
    repair_cmd.add_argument("target")
    repair_cmd.add_argument(
        "resolution",
        help="required: the toolchain does not choose for a generated-zone divergence",
    )

    blueprints_cmd = sub.add_parser("blueprints", help="list the blueprint catalog (input B)")
    blueprints_cmd.add_argument("--catalog", type=Path, default=None)

    brief_cmd = sub.add_parser("brief", help="print the brief the code-generation agent gets")
    brief_cmd.add_argument("project", type=Path)
    brief_cmd.add_argument("--request", default=None, help="what the user asked for (input A)")
    brief_cmd.add_argument("--blueprint", default=None, help="a catalog blueprint id (input B)")
    brief_cmd.add_argument("--catalog", type=Path, default=None)

    record_cmd = sub.add_parser("record", help="gate a generation and log its failure modes")
    record_cmd.add_argument("project", type=Path)
    record_cmd.add_argument("--source", choices=["chat", "blueprint"], required=True)
    record_cmd.add_argument("--request", default="")
    record_cmd.add_argument("--blueprint", default=None)
    record_cmd.add_argument(
        "--observe",
        action="store_true",
        help="also run the observable checks -- this imports and runs the project",
    )

    failures_cmd = sub.add_parser("failures", help="tally the agent's logged failure modes")
    failures_cmd.add_argument("project", type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    # No arguments means sidecar mode. Tauri spawns the binary bare, so this branch is
    # load-bearing: a parser that errored on an empty argv would kill the app at startup.
    if not args:
        return serve_forever()

    parsed = build_parser().parse_args(args)
    if parsed.command == "strip":
        return run_strip(parsed.project, parsed.destination)
    if parsed.command == "graph":
        return run_graph(parsed.project)
    if parsed.command == "check":
        return run_check(parsed.project, parsed.observe)
    if parsed.command == "snapshot":
        return run_snapshot(parsed.project)
    if parsed.command == "status":
        return run_status(parsed.project)
    if parsed.command == "set-knob":
        return run_set_knob(parsed.project, parsed.node, parsed.knob, parsed.value)
    if parsed.command == "repairs":
        return run_repairs(parsed.project)
    if parsed.command == "repair":
        return run_repair(parsed.project, parsed.code, parsed.target, parsed.resolution)
    if parsed.command == "blueprints":
        return run_blueprints(parsed.catalog)
    if parsed.command == "brief":
        return run_brief(parsed.project, parsed.request, parsed.blueprint, parsed.catalog)
    if parsed.command == "record":
        return run_record(
            parsed.project, parsed.source, parsed.request, parsed.blueprint, parsed.observe
        )
    if parsed.command == "failures":
        return run_failures(parsed.project)

    build_parser().print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
