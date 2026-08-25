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
    uv run python -m aibuilder_core env <project>
    uv run python -m aibuilder_core env-up <project>
    uv run python -m aibuilder_core env-down <project>
    uv run python -m aibuilder_core run <project> [--port N]
    uv run python -m aibuilder_core run-status <project>
    uv run python -m aibuilder_core logs <project>
    uv run python -m aibuilder_core call <project> <path>
    uv run python -m aibuilder_core stop <project>
    uv run python -m aibuilder_core work <project>
    uv run python -m aibuilder_core work-status <project>
    uv run python -m aibuilder_core work-logs <project>
    uv run python -m aibuilder_core work-stop <project>
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
    environment_status,
    mcp_call,
    mcp_inspect,
    repair_divergence,
    repairs_available,
    run_call,
    run_logs,
    run_start,
    run_state,
    run_stop,
    services_start,
    services_stop,
    snapshot_status,
    take_project_snapshot,
    work_logs,
    work_start,
    work_state,
    work_stop,
    write_body,
    write_knob,
)
from aibuilder_core.catalog import CATALOG_ENV
from aibuilder_core.gate import check_graph, summarize
from aibuilder_core.handlers import dispatch
from aibuilder_core.observe import run_observations
from aibuilder_core.project import read_project
from aibuilder_core.protocol import (
    ProtocolError,
    decode_request,
    encode_error,
    encode_result,
)
from aibuilder_core.runner import stop_everything_started_here
from aibuilder_core.session import close_everything_started_here
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
    """The sidecar. Ends whatever it started before it goes (P13).

    `atexit` covers the ordinary paths, and this covers the one that matters most: the shell
    closing our stdin because the window went away. A session that ends leaves nothing
    running -- and a session that is killed outright leaves the state file, which is how the
    next one finds the orphan.
    """
    log("ready")
    try:
        with contextlib.suppress(KeyboardInterrupt):
            serve(sys.stdin, sys.stdout)
    finally:
        stop_everything_started_here()
        # A session is the sidecar's lifetime (Q16): ending here ends the agent too, or a
        # closed window leaves somebody's agent running with nothing to talk to.
        close_everything_started_here()
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
    print(json.dumps(read_project(project).to_dict(), indent=2))
    return 0


def run_check(project: Path, observe: bool) -> int:
    """Run the gate and print its diagnostics, addressed.

    Always exits 0 in soft mode: a violation is a badge and a repair offer, not a refusal
    (§7). Hard mode is what a caller uses when it wants a failing exit code.
    """
    graph = read_project(project)

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


def run_set_body(project: Path, node: str, function: str, source_file: str) -> int:
    """Write a new body for one editable function, read from a file or from stdin.

    From a file rather than an argument: a body is many lines, and a shell is the wrong
    place to quote one. `-` reads stdin, which is what a pipe wants.
    """
    source = sys.stdin.read() if source_file == "-" else Path(source_file).read_text("utf-8")

    result = write_body(project, node, function, source)
    if not result["written"]:
        print(f"refused: {result['refused']}")
        for diagnostic in result["diagnostics"]:
            print(f"  {diagnostic['code']} -- {diagnostic['message']}")
        return 1

    print(f"{function} rewritten in {result['file']}")
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


def run_env(project: Path) -> int:
    """Describe the environment. Reads only -- nothing here starts anything (P11)."""
    environment = environment_status(project)["environment"]

    print(f"interpreter: {environment['interpreter']} ({environment['interpreter_origin']})")
    if environment["compose_file"] is None:
        print("services: none declared (no compose file)")
    elif environment["docker_unavailable"]:
        print(f"services: declared in {environment['compose_file']}")
        print(f"  cannot be read: {environment['docker_unavailable']}")
    else:
        for service in environment["services"]:
            ports = ", ".join(str(port) for port in service["ports"]) or "no published port"
            state = "answering" if service["reachable"] else "nothing answers"
            print(f"  {service['name']}: {state} ({ports})")
    return 0


def run_env_up(project: Path) -> int:
    """Bring the declared services up, because someone asked."""
    result = services_start(project)
    print(result["detail"])
    return 0 if result["ok"] else 1


def run_env_down(project: Path) -> int:
    result = services_stop(project)
    print(result["detail"])
    return 0 if result["ok"] else 1


def run_start_cmd(project: Path, port: int | None) -> int:
    """Start the application and say where it is listening."""
    result = run_start(project, None, port)
    print(result["detail"])
    if result["logs"]:
        print(result["logs"])
    return 0 if result["ok"] else 1


def run_stop_cmd(project: Path) -> int:
    result = run_stop(project)
    print(result["detail"])
    return 0 if result["ok"] else 1


def run_status_cmd(project: Path) -> int:
    result = run_state(project)
    print(result["detail"])
    return 0 if result["ok"] else 1


def run_logs_cmd(project: Path) -> int:
    """Print what the application has written so far. Polled, like everything here."""
    result = run_logs(project, 0)
    print(result["logs"] or result["detail"], end="")
    return 0 if result["ok"] else 1


def run_call_cmd(project: Path, path: str, method: str) -> int:
    result = run_call(project, path, method)
    if not result["ok"]:
        print(result["detail"])
        return 1
    print(f"HTTP {result['status']}")
    print(result["body"])
    return 0


def run_work_cmd(project: Path) -> int:
    """Start a worker and say what answered. Refuses if the broker is not up (P11)."""
    result = work_start(project)
    print(result["detail"])
    if result["logs"]:
        print(result["logs"])
    return 0 if result["ok"] else 1


def run_work_status_cmd(project: Path) -> int:
    result = work_state(project)
    print(result["detail"])
    return 0 if result["ok"] else 1


def run_work_logs_cmd(project: Path) -> int:
    result = work_logs(project, 0)
    print(result["logs"] or result["detail"], end="")
    return 0 if result["ok"] else 1


def run_work_stop_cmd(project: Path) -> int:
    result = work_stop(project)
    print(result["detail"])
    return 0 if result["ok"] else 1


def run_inspect_cmd(project: Path, node: str) -> int:
    """Connect to a consumed server and print what it offers. Never a side effect (P11)."""
    result = mcp_inspect(project, node)
    print(f"{result['status']}: {result['detail']}")
    allowed = set(result["allowed"])
    for tool in result["tools"]:
        mark = "allowed" if not allowed or tool["name"] in allowed else "      "
        print(f"  {mark} {tool['name']} -- {tool['description']}")
    for name in result["missing"]:
        print(f"  MISSING {name} -- this project may call it and the server does not offer it")
    return 0 if result["ok"] else 1


def run_mcp_call_cmd(project: Path, node: str, tool: str, raw: str) -> int:
    """Call one tool with arguments a person typed. Read as JSON, never invented."""
    try:
        arguments = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"the arguments are not JSON: {exc}")
        return 2
    if not isinstance(arguments, dict):
        print("the arguments must be a JSON object")
        return 2

    result = mcp_call(project, node, tool, arguments)
    print(f"{result['status']}: {result['detail']}")
    if result["result"]:
        print(result["result"])
    return 0 if result["ok"] else 1


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

    body_cmd = sub.add_parser("set-body", help="write a new body for an editable function")
    body_cmd.add_argument("project", type=Path)
    body_cmd.add_argument("node")
    body_cmd.add_argument("function", help="the dotted path of the function to rewrite")
    body_cmd.add_argument("source", help="a file holding the replacement, or - for stdin")

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

    env_cmd = sub.add_parser("env", help="describe the project's interpreter and services")
    env_cmd.add_argument("project", type=Path)

    env_up_cmd = sub.add_parser("env-up", help="bring the project's declared services up")
    env_up_cmd.add_argument("project", type=Path)

    env_down_cmd = sub.add_parser("env-down", help="take the project's services down")
    env_down_cmd.add_argument("project", type=Path)

    run_cmd = sub.add_parser("run", help="start the project's application")
    run_cmd.add_argument("project", type=Path)
    run_cmd.add_argument("--port", type=int, default=None)

    run_status = sub.add_parser("run-status", help="is the application running?")
    run_status.add_argument("project", type=Path)

    logs_cmd = sub.add_parser("logs", help="what the application has printed")
    logs_cmd.add_argument("project", type=Path)

    call_cmd = sub.add_parser("call", help="call the running application")
    call_cmd.add_argument("project", type=Path)
    call_cmd.add_argument("path", nargs="?", default="/")
    call_cmd.add_argument("--method", default="GET")

    stop_cmd = sub.add_parser("stop", help="stop the application")
    stop_cmd.add_argument("project", type=Path)

    work_cmd = sub.add_parser("work", help="start a worker for the project's queue")
    work_cmd.add_argument("project", type=Path)

    work_status = sub.add_parser("work-status", help="is a worker answering the queue?")
    work_status.add_argument("project", type=Path)

    work_logs_cmd = sub.add_parser("work-logs", help="what the worker has printed")
    work_logs_cmd.add_argument("project", type=Path)

    work_stop_cmd = sub.add_parser("work-stop", help="stop the worker")
    work_stop_cmd.add_argument("project", type=Path)

    inspect_cmd = sub.add_parser("inspect", help="connect to a consumed MCP server")
    inspect_cmd.add_argument("project", type=Path)
    inspect_cmd.add_argument("node", help="the id of the mcp.server node to connect to")

    tool_cmd = sub.add_parser("tool", help="call one tool on a consumed MCP server")
    tool_cmd.add_argument("project", type=Path)
    tool_cmd.add_argument("node")
    tool_cmd.add_argument("tool")
    tool_cmd.add_argument("arguments", nargs="?", default="{}", help="a JSON object")

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
    if parsed.command == "set-body":
        return run_set_body(parsed.project, parsed.node, parsed.function, parsed.source)
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
    if parsed.command == "env":
        return run_env(parsed.project)
    if parsed.command == "env-up":
        return run_env_up(parsed.project)
    if parsed.command == "env-down":
        return run_env_down(parsed.project)
    if parsed.command == "run":
        return run_start_cmd(parsed.project, parsed.port)
    if parsed.command == "run-status":
        return run_status_cmd(parsed.project)
    if parsed.command == "logs":
        return run_logs_cmd(parsed.project)
    if parsed.command == "call":
        return run_call_cmd(parsed.project, parsed.path, parsed.method)
    if parsed.command == "stop":
        return run_stop_cmd(parsed.project)
    if parsed.command == "work":
        return run_work_cmd(parsed.project)
    if parsed.command == "work-status":
        return run_work_status_cmd(parsed.project)
    if parsed.command == "work-logs":
        return run_work_logs_cmd(parsed.project)
    if parsed.command == "work-stop":
        return run_work_stop_cmd(parsed.project)
    if parsed.command == "inspect":
        return run_inspect_cmd(parsed.project, parsed.node)
    if parsed.command == "tool":
        return run_mcp_call_cmd(parsed.project, parsed.node, parsed.tool, parsed.arguments)

    build_parser().print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
