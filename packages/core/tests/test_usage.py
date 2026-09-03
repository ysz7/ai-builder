"""What a run cost, measured in the run's own child process (Phase 11).

The provider here is a stand-in package written into the project — a `Messages.create` that
returns a `usage` object and nothing else. That is deliberate: the claim under test is "the
meter counts what the project's own code asked a client for", and a real API call would test
somebody's network and bill somebody's account to prove it.

Three of these are the plan's acceptance criteria, stated as tests:

* an unknown model shows tokens and **no** dollar figure;
* deleting `.framestack/` loses history and nothing else;
* **no cost instrumentation appears in user code** — the project is byte for byte what it was.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from contract import validate, wire_form

from framestack_core.api import USAGE_SCHEMA, usage_read
from framestack_core.run import last_run, start_run
from framestack_core.usage import LEDGER_PATH, price_of, read_usage

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "full"

PATIENCE = 120

#: A provider client, in as little as one can be. The meter patches `Messages.create`, so
#: what matters is the shape of the answer: a `model` and a `usage` with two counts.
CLIENT = """
class _Usage:
    def __init__(self, given, back):
        self.input_tokens = given
        self.output_tokens = back


class _Answer:
    def __init__(self, model, given, back):
        self.model = model
        self.usage = _Usage(given, back)
        self.content = []


class Messages:
    def create(self, model="{model}", **keywords):
        return _Answer(model, 1000, 120)
"""

#: An agent that calls it twice. Ordinary code: it imports a client and uses it, and there is
#: nothing in it that knows this application exists.
AGENT = '''"""An agent that talks to a model."""

from anthropic.resources.messages import Messages


def run(message: str, **kw) -> str:
    client = Messages()
    first = client.create()
    second = client.create()
    return f"{first.model} answered twice ({second.model})"
'''


def project(tmp_path: Path, model: str = "claude-opus-5") -> Path:
    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack"))

    where = root / "anthropic" / "resources"
    where.mkdir(parents=True)
    (root / "anthropic" / "__init__.py").write_text("", encoding="utf-8")
    (where / "__init__.py").write_text("", encoding="utf-8")
    (where / "messages.py").write_text(CLIENT.replace("{model}", model), encoding="utf-8")
    (root / "agent" / "__init__.py").write_text(AGENT, encoding="utf-8")
    return root


def run(root: Path) -> None:
    """Press `Run` and wait for it, through the polling that is the contract."""
    started = start_run(root, "agent", "run")
    assert started.ok, started.detail
    for _ in range(PATIENCE * 10):
        answer = last_run(root, "agent")
        if not answer.running:
            return
        time.sleep(0.1)
    raise AssertionError("the run never finished")


# -- what was measured ---------------------------------------------------------------------


def test_a_run_records_one_step_per_call(tmp_path: Path) -> None:
    """The tokens are the provider's own numbers, and the steps are in the order they happened."""
    root = project(tmp_path)

    run(root)
    answer = read_usage(root, "agent")

    assert answer.ok is True
    assert [(call.input, call.output) for call in answer.calls] == [(1000, 120), (1000, 120)]
    assert answer.tokens == 2240
    assert answer.calls[0].model == "claude-opus-5"


def test_the_dollars_are_arithmetic_over_a_table(tmp_path: Path) -> None:
    """Nothing stored is a price. The table is the only place a dollar figure comes from,
    so correcting it corrects the history it is applied to."""
    root = project(tmp_path)

    run(root)
    answer = read_usage(root, "agent")

    one = price_of("claude-opus-5", 1000, 120)
    assert one is not None
    assert answer.cost is not None
    assert abs(answer.cost - 2 * one) < 1e-12


def test_an_unknown_model_shows_tokens_and_no_dollar_figure(tmp_path: Path) -> None:
    """An acceptance criterion, and the rule the whole file follows: never a guessed number.

    `None` rather than zero, in both places. `$0.00` for a run nobody has a price for is a
    false statement where "we do not know" is the true one.
    """
    root = project(tmp_path, model="somebody-elses-model-v9")

    run(root)
    answer = read_usage(root, "agent")

    assert answer.tokens == 2240
    assert answer.cost is None
    assert all(call.cost is None for call in answer.calls)
    # Named, so a panel can say which model is the reason the figure is missing.
    assert answer.unpriced == ("somebody-elses-model-v9",)


def test_a_dated_snapshot_is_the_same_model_at_the_same_price() -> None:
    """Refusing to price `claude-opus-5-20260101` would be pedantry rather than honesty."""
    assert price_of("claude-opus-5-20260101", 1_000_000, 0) == 5.0
    assert price_of("gpt-something", 1_000_000, 0) is None


def test_only_the_last_run_is_reported(tmp_path: Path) -> None:
    """The panel answers "what did this cost", about the run a person just watched. The
    ledger keeps the rest; the reading is of one run."""
    root = project(tmp_path)

    run(root)
    run(root)
    answer = read_usage(root, "agent")

    assert len(answer.calls) == 2


# -- what it must not touch ------------------------------------------------------------------


def test_no_cost_instrumentation_appears_in_user_code(tmp_path: Path) -> None:
    """The acceptance criterion, and invariant 6 stated in this phase's terms.

    Everything the meter is lives in the child's driver, which is written into `.framestack/`
    and deleted with it. Delete Framestack and the project is what it was.
    """
    root = project(tmp_path)
    before = {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*.py"))
        if ".framestack" not in path.parts and "__pycache__" not in path.parts
    }

    run(root)

    after = {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*.py"))
        if ".framestack" not in path.parts and "__pycache__" not in path.parts
    }
    assert after == before


def test_deleting_the_state_directory_loses_history_and_nothing_else(tmp_path: Path) -> None:
    """The third acceptance criterion. The ledger is Framestack's own record of runs it
    started — not project data, and not a second source of truth about the code."""
    root = project(tmp_path)
    run(root)
    assert (root / LEDGER_PATH).is_file()

    shutil.rmtree(root / ".framestack")

    assert read_usage(root, "agent").calls == ()
    # And the project still runs, because nothing about running it was in there.
    run(root)
    assert len(read_usage(root, "agent").calls) == 2


def test_a_project_that_has_never_been_run_is_not_a_failure(tmp_path: Path) -> None:
    root = project(tmp_path)

    answer = read_usage(root, "agent")

    assert answer.ok is True
    assert answer.calls == ()
    assert answer.cost is None


def test_a_project_with_no_provider_at_all_measures_nothing_and_still_runs(
    tmp_path: Path,
) -> None:
    """The meter patches a client only where one is importable. A project that talks to no
    model has an empty ledger, which is the truth about it."""
    root = tmp_path / "plain"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("__pycache__", ".framestack"))

    run(root)

    assert last_run(root, "agent").outcome is not None
    assert read_usage(root, "agent").calls == ()


# -- the wire ---------------------------------------------------------------------------------


def test_the_payload_matches_the_contract(tmp_path: Path) -> None:
    root = project(tmp_path)
    run(root)

    validate(wire_form(usage_read(root, "agent")), USAGE_SCHEMA)
    # A node nobody ran, and a project that is not there: both are results, same shape.
    validate(wire_form(usage_read(root, "rag")), USAGE_SCHEMA)
    validate(wire_form(usage_read(tmp_path / "nowhere", "agent")), USAGE_SCHEMA)
