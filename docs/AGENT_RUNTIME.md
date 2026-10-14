# Hierarchical agent runtime

What it is, the rules it enforces, how to run it, and what it does **not** do. Everything stated as a guarantee has a test
(`tests/test_agent_runtime.py`, `tests/test_agent_execution.py`) or an evaluation scenario (`eval/agent_eval.py`).

## Shape

```
objective ─► Supervisor (L0) ─► structured Plan ─► validator ─► workflow definition ─► engine
                 plans, holds no tools     typed tasks, deps,        same rules as a hand-built      scheduler + approvals
                                           ops, budgets              workflow in the studio

engine ─► task (agent.task node) ─► agent runner ─► operation pipeline ─► tool (L3) ─► mock HRMS / ERP / ticketing
          one per plan task          scripted or      validate → authorize → policy →
                                     model-driven     approve → idempotency → run → validate → audit
```

| Level | Role | Holds tools? | Configured in |
|---|---|---|---|
| 0 Organization supervisor | interprets the objective, plans, delegates | **No** (enforced; may not hold write/destructive either) | agent registry |
| 1 Department coordinator | owns a department; its tools are the **ceiling** for its specialists | yes | agent registry |
| 2 Specialist | narrow responsibility, typed output | subset of its coordinator's tools | agent registry |
| 3 Tool | the only thing that touches a business system | n/a | tool registry (`core/platform/tools.py`) |

Workflows need not use every level: a task may be assigned to a coordinator directly. Hierarchy is data, not code: add a
department by creating agents in the registry (Agents page or `POST /agents`). The built-in HR / Finance / IT hierarchy is seeded
only for ids that never existed, so administrator edits survive restarts.

## Agent registry

`agents` (lifecycle) and `agent_versions` (immutable configuration) are separate from execution state (`node_runs`). A
configuration is plain validated data (pydantic `extra="forbid"`): identity, level/parent, capabilities, model + provider +
tiers + fallback, instructions, JSON-Schema input/output (no `$ref`), allowed tools and connectors, read/write/destructive
permissions, memory (task-scoped only), token/call/time budgets, retry policy, review requirement, status. There is no code,
no templating that is evaluated, and no import path in a configuration.

Server-side rules on every write: unknown parent or tool; level/parent mismatch; parent cycles; the supervisor holding tools or
write permission; a specialist holding a tool its coordinator lacks; a tool whose effect is not covered by the agent's
permissions; narrowing a coordinator below what its specialists hold; disabling an agent that still has active children.
Editing writes version n+1. **A run records the version of every agent it may use (`runs.agent_snapshot`)**; disabling an agent
still blocks it mid-run because its live status is re-checked before every operation.

## Planning

A plan (`core/platform/planner.py`) is typed data: objective, input fields, tasks with `agent_id`, `depends_on`, scripted
`operations` (`{tool, arguments}` with `{{trigger.x}}` / `{{nodes.t.output…}}` references), required capabilities, risk estimate,
complexity, criticality, evidence requirement, completion criteria, timeout, and constraints. The schema forbids unknown
fields, so **a plan or a model-written plan cannot carry permissions, policy overrides or tool grants**; authority comes only
from the registry. Constraints can lower server limits, never raise them.

Planners: `deterministic` (keyword-scored playbooks for expense / onboarding / incident; an objective that matches nothing is a
*planning failure*, not a guess), `llm` (supervisor's model; validation errors, not the model's own output, are fed back; at most
2 repair rounds), `structured` (you supply the plan), and `auto` (model if the supervisor has one and it answers, otherwise
deterministic, recorded in the plan's `note`).

Validation reuses the workflow validator, so a plan and a hand-built workflow are held to identical rules: unknown/inactive
agents, supervisor assigned work, dangling or cyclic dependencies, bad references, unknown tools, a tool outside the agent's
entry, an effect the agent lacks, a role the tool refuses, missing capabilities, identical side-effecting calls repeated in one
task, bad arguments, an agent's required reviewer missing downstream, and worst-case tool-call / token demand against the plan's
limits. Each issue carries a `category`: `planning_failure`, `policy_rejection`, or `budget_exceeded`. Runtime failures use the
classes below. `POST /plans/{id}/execute` validates again.

## Scheduling and failure rules

* A node runs only when **every** upstream node is `completed`. If any upstream node failed, was skipped, rejected or cancelled,
  the node is `skipped`. There is no "run anyway": an empty or failed dependency is never silently ignored.
* Independent ready nodes run in parallel on a worker pool, never above the run's `max_concurrency`.
* A failed `required` task fails the run. A failed `optional` task does not: the run ends **`partial`**.
* A human rejection ends that path (`rejected`); independent paths still finish.
* **Cancel**: no new node starts; running tasks stop at their next operation boundary; parked/pending nodes and their open
  approvals are cancelled. An operation already in flight is never interrupted halfway.
* Timeouts: each task has a deadline (agent budget, optionally tighter per task) that propagates to model and tool calls.
  Pauses for human approval do not count against it.
* Retries: only **reads** and model calls are retried, on transient failures, with bounded exponential backoff
  (`min(base·2ⁿ, cap)`), each retry visible as a `node.retry` event. **Writes are never auto-retried.**
* Conditional branches are not implemented (the workflow schema has none).

Failure classes on a node: `policy_rejection`, `validation_error`, `execution_failure`, `insufficient_evidence`,
`budget_exceeded`, `timeout`, `provider_error`, `approval_rejected`, `outcome_unknown`, `cancelled`, `upstream_failed`.

## The operation pipeline (`core/platform/operations.py`)

Every tool call, scripted or proposed by a model, takes the same path: **validate arguments** (pydantic, extra fields rejected)
→ **authorize** from the registry snapshot and the authenticated user's *database* role (agent allowed the tool? agent holds the
effect permission? role allowed? employees only on their own record) → **policy decision** (existing engine, fed the agent's
allow-list; any `destructive` tool is forced to RULE-DESTRUCTIVE-001, Director/Admin approval) → **approval gate** (task is parked,
nothing executes, the approval stores the exact arguments and the evidence gathered so far) → **idempotency claim** (unique key per
run·node·operation slot) → **execute** under a timeout in a tool thread → **validate output** → **record + audit + event**.
Authorization runs again after an approval. Nothing a model says reaches this code as authority: tool results are quoted to the
model inside `<tool_result>` blocks marked untrusted, and the system prompt is identical on every call.

## Durability and resumption

* State lives in the database: node status, a per-task `checkpoint` (resolved operations, completed results, model conversation,
  usage, the pending operation), `tool_executions`, approvals, and the numbered event log. No essential state is in memory,
  Streamlit session state, or the browser.
* Approval → resume: the decision commits, exactly one caller observes the transition and re-drives the run; the node is claimed
  with an atomic `awaiting_approval → running`, so a duplicate resume is a no-op. A model-driven task resumes from its saved
  conversation instead of asking the model again.
* Restart (`recover_interrupted_runs`, run at API start): a decision committed just before a crash is picked up; a task whose
  operations are all recorded replays them (`tool.replayed`) and continues; **a write that started but whose result was never
  recorded is failed as `outcome_unknown` and not re-sent**; legacy single-tool nodes caught mid-flight are failed the same way.
* **This is at-most-once delivery, not exactly-once.** The mock systems offer no idempotency token, so a crash between the call and
  the record cannot be told apart from a call that never happened; the runtime chooses to report rather than repeat.
* Tool timeouts cannot kill a thread: a timed-out write is reported `outcome_unknown`, and the abandoned thread records what
  really happened in `tool_executions` when it finishes, so an operator can reconcile.

## Model gateway (`core/platform/gateway.py`)

Adapters: Ollama (`/api/chat`), OpenAI-compatible (`/chat/completions`, optional), and a scripted provider for tests. Per-agent
model config with `small | default | large` tiers chosen by task complexity, a fallback provider, request timeouts, bounded
rate-limit handling (honours `Retry-After`, at most twice), structured-output validation with bounded repair, and per-task
budgets on calls and tokens checked **before** each call.

Usage is recorded with provenance: `provider` (the server reported counts), `estimated` (derived from text length), `mixed`, or
`none`. **No cost is ever computed** (`cost_usd` is always `null`). There is no response cache: a correct one needs tenant,
authorization and freshness keys that do not exist yet, and a shared cache would be unsafe.

## Running it

```bash
python -m venv .venv && . .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn apps.api.main:app --port 8000      # applies migrations, seeds the registry and dev accounts
cd apps/console && npm install && npm run dev        # http://localhost:5173
```

**Database migrations** (Alembic; `migrations/`, `alembic.ini`) run automatically at API start. A database created by an earlier
build is upgraded in place (tables are only created if missing; data is preserved; `foreign_key_check` must come back empty).
Manual: `alembic -x url=sqlite:///./hacfew_platform.db upgrade head` (or `python -c "from core.platform.db import init_platform_db as i; i()"`).
Back up `hacfew_platform.db` first; there is a downgrade for 0002 but it drops the agent tables.

```bash
python -m pytest                                              # backend: 103 tests
cd apps/console && npm run typecheck && npm test              # console
python scripts/smoke_agent_runtime.py http://127.0.0.1:8000   # live API: async workers, SSE, approval round trip
python eval/agent_eval.py                                     # measured evaluation -> eval/agent_eval_results.json
npx playwright install chromium && npm run e2e && npm run e2e:agent
```

## Evaluation

`eval/agent_eval.py` (suite 1.0.0) runs 22 scenarios (functional, security, budget, durability) against the real runtime on throwaway
copies of the databases, and writes what it **observed** to `eval/agent_eval_results.json`, including every failing scenario.
Model-free by default; scenarios marked `[scripted model]` test the runtime's handling of model behaviour, not any model's quality.
A real model is evaluated only with `--model ollama:<name>` and only if the provider answers; otherwise it is reported `not_run`
(it is `not_run` in the committed results). For LLM-dependent runs the report records model, prompt versions (`planner-v1`,
`agent-v1`), test objectives and criterion (does the plan validate). Deterministic security requirements never depend on a model.

The suite was checked for falsifiability: disabling the concurrency limit fails B3; disabling every authorization layer fails 7
scenarios (a forbidden tool really executes). Note that several layers deny a forbidden tool (registry authorization, the policy
engine allow-list, the static department table), so disabling a single one does not change an outcome by design.

**The older `eval/run_benchmark.py` is not a measurement.** Its `SingleAgentBaseline` returns scripted failures (e.g. it always
reports a safety breach for red-team scenarios), so the "100 % vs 60 %" figures in the README and report are not results of
running a competing system. Use `eval/agent_eval.py` for anything you cite.

## Limitations (not implemented, not verified)

* **Only SQLite was exercised.** The migrations and the engine were not run against PostgreSQL, and the Docker image changes
  (migrations copied in, `jsonschema` added) were not built. The Dockerfile base is Python 3.10; development used 3.11.
* **No model was run.** The Ollama and OpenAI-compatible adapters are tested against mocked HTTP transports only. Planner and agent
  quality with a real model is unmeasured; the model-backed planner has never produced a plan from a real model here.
* Threads, not asyncio. Cancellation cannot interrupt an in-flight tool call. One process drives a run (locks are process-local);
  node claims are atomic in the database, but running several API processes against one database is untested.
* SQLite serialises every transaction (`BEGIN IMMEDIATE`) to make concurrent workers safe; fine for development, use PostgreSQL
  for real concurrency. The bundled mock systems' calls are serialised by a lock.
* Audit-chain appends are serialised per process only (unchanged from before).
* The checkpoint stores task data unredacted so a task can resume; the API never returns it, but it needs the same database
  protection as the rest of the platform state. Tool results replayed from `tool_executions` have secret-named keys masked.
* Review requirements are structural (the reviewer's task must exist downstream); there is no semantic check of the review.
* Evidence means citations / record ids returned by tools; claim-level grounding is not verified.
* Policy rules are still the three-department rules in `core/governance/policy_engine.py` plus the destructive-tool rule; new
  departments get agents and tools but not new business rules without code.
* No long-term agent memory, no response cache, no MCP, connector credential store, user-management UI, or industry packs. The
  agent and tool registries are the extension points for those; none of them is implemented.
