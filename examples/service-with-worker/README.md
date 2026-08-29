# Example: a service with background work

The project P14 is proven on: a FastAPI service that hands a report off to a queue instead
of building it inside the request, a celery worker to run it, and a timed sweep beside it.

Two top-level groups, not one. `api` is the service; `work` is the background work — a
subsystem of its own, because a task outlives the request that queued it and runs in a
process the service never starts. What connects them is a **flow arrow**, and only after a
run has drawn one:

```
reports.request ──observed──▶ work.report
```

Nothing declared that edge and nothing parsed `.delay(...)` out of the route. A test queued a
report, the task ran, and the run is what drew it (Q9).

## What proves what

| Node | Proven by |
| --- | --- |
| `work.report`, `work.sweep` | a run that entered them — the project's own tests |
| `work.queue` | the broker answering |
| `work.schedule` | every timed entry naming a task the queue knows |
| `work` | the queue being assembled with tasks on it |

**"The task works" and "the queue delivers" are different claims**, and the graph keeps them
apart on purpose. The suite runs tasks in celery's eager mode, which is honest about what it
proves: the task's code, with real input, from the code path that queues it. It proves
nothing about delivery. Delivery is the queue node's own check and the worker button.

With the broker down, every node here is green or unproven and none is broken:

```bash
uv run python -m framestack_core check examples/service-with-worker --observe
```

## Running it

Nothing starts on its own — not the broker, and not the worker. The worker **refuses** to
start while the broker is down rather than bringing it up on the way past, because a worker
retrying against a dead broker looks, from the outside, exactly like one that is working.

```bash
uv run python -m framestack_core env-up examples/service-with-worker    # the broker
uv run python -m framestack_core work examples/service-with-worker      # the worker
uv run python -m framestack_core run examples/service-with-worker       # the service
uv run python -m framestack_core call examples/service-with-worker /health
uv run python -m framestack_core work-logs examples/service-with-worker
uv run python -m framestack_core work-stop examples/service-with-worker
uv run python -m framestack_core stop examples/service-with-worker
uv run python -m framestack_core env-down examples/service-with-worker
```

A worker publishes no port, so "is it up?" is asked of the **queue** — has anything answered
it? — rather than of a socket. A log line saying `ready` is a string a process chose to
print; a reply that came back through the broker is the thing itself.

## Two conventions the checks depend on

**The task's carrier stays a plain function**, and registering it is generated assembly
(`app.task(name="work.report")(build_report)`), the same split the routes follow. A carrier
wrapped in a task decorator is no longer the function the graph named, and a run through it
could not be seen.

**The queue's knobs reach celery's own configuration** (`worker_concurrency`,
`task_time_limit`). That is what the builder asks when it runs a worker, so the button and
the knob cannot drift apart — a knob the library never sees would be decoration.
