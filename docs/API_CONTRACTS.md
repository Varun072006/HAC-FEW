# HAC-FEW Platform API contracts (v1)

Base path `/api/v1`. The authoritative, machine-readable contract is the FastAPI OpenAPI document
(`/openapi.json`). The console's TypeScript types are generated from it:

```bash
cd apps/console && npm run gen:api     # exports openapi.json via scripts/export_openapi.py, then openapi-typescript
```

Request/response models live in [`apps/api/schemas.py`](../apps/api/schemas.py).

## Authentication

| | |
|---|---|
| `POST /auth/login` `{username, password}` | `200 {access_token, token_type, expires_in, user}`; `401` on bad credentials; `429` after 5 failures in 5 minutes for a username |
| `GET /auth/me` | Current user and their server-side permission list |
| `GET /auth/config` | `{environment, dev_accounts}`. `dev_accounts` is empty unless `HACFEW_ENV=development` |

* Bearer JWT (HS256), 8 h by default (`HACFEW_TOKEN_TTL_SECONDS`). The token carries only `sub`; **the role is always read from the
  database on every request**, so deactivating a user or changing a role takes effect immediately and a client can never assert a role.
* Passwords are scrypt-hashed. Production requires `HACFEW_JWT_SECRET` (≥ 32 chars) and seeds no accounts.
* Every protected route declares a permission (`require("...")`). `403` is returned and an `authz.denied` audit event is written when the
  permission is missing. Runs/approvals that a caller may not see return `404`, not `403`, so IDs cannot be probed.

## Errors

`{"detail": "message"}` for most errors. Run creation failures are `422 {"detail": {"message", "issues": [{severity, code, message, node_id}]}}`.
Conflicts (`409`): stale workflow version, an approval that is already decided, a repeated decision by the same person, or a concurrent
decision on the same slot.

## Routes

| Method & path | Permission | Notes |
|---|---|---|
| `GET /catalog/nodes` | `workflow:read` | Executable node types, params, outputs, allowed roles |
| `GET /templates` | `workflow:read` | Expense, onboarding, incident-triage |
| `POST /workflows/validate` | `workflow:read` | Same validator the engine runs before every run |
| `GET/POST /workflows`, `GET/PUT/DELETE /workflows/{id}` | read / `workflow:write` | `PUT` needs `expected_version` (optimistic concurrency). Delete is refused once runs exist |
| `POST /workflows/{id}/runs` `{inputs}` | `workflow:run` | `202`; validates definition **and** the caller's role against each node; executes on a worker |
| `GET /runs`, `GET /runs/{id}` | `run:read` (+ `run:read_all` for others' runs) | Detail includes the immutable definition snapshot, node runs and approvals |
| `GET /runs/{id}/events?after=<seq>` | `run:read` | Cursor feed, see below |
| `GET /approvals?status=`, `GET /approvals/{id}` | `run:read` | Deciders see all; requesters only their own. `can_decide` is computed by the server |
| `POST /approvals/{id}/decision` `{decision: approve|reject, comment}` | `approval:decide` | See approval rules |
| `GET /agents`, `/connectors`, `/policies` | `registry:read`, `connector:read`, `policy:read` | Read from the live engine, not copies |
| `GET /audit`, `GET /audit/verify` | `audit:read` | Hash-chained audit trail and verifier |
| `GET /usage` | `run:read_all` | Aggregates over persisted node runs. `llm_calls` is 0: the engine is rule-based |
| `GET /overview` | `run:read` | Counts scoped to what the caller may see |
| `GET /org` | `org:admin` | Environment and accounts |

`POST /workflows/run` (legacy keyword planner) is **disabled** (`410`) unless `HACFEW_ENABLE_LEGACY_API=1`, because it trusts a client-supplied role.

## State machines

Run: `queued → running → (awaiting_approval ⇄ running) → completed | failed | rejected`  
Node: `pending → running → completed | failed`, `pending → skipped` (an upstream node failed/was rejected/skipped),
`running → awaiting_approval → running → completed | failed`, `awaiting_approval → rejected`.

## Execution events

`GET /runs/{id}/events?after=N` returns events with `seq > N` in order, plus `next_after`, `run_status` and `terminal`.
Poll with `after=next_after` until `terminal` is true (the console polls every 1 s while a run is live, 3 s while it waits on a human).
Events are persisted, so the feed is identical after a refresh or backend restart. Payloads are secret-redacted when stored and
PII-masked per viewer when returned.

| `type` | `node_id` | `data` |
|---|---|---|
| `run.created` | | `workflow_id, workflow_version, started_by, inputs` |
| `run.started` / `run.resumed` | | |
| `node.started` / `node.resumed` | ✓ | `type, agent` / `approval_id` |
| `policy.decision` | ✓ | `allowed, risk_level, rule_id, reason, requires_human_approval` |
| `tool.call` | ✓ | `tool, agent, params, attempt?, approved_by?` |
| `tool.result` | ✓ | `tool, success, latency_ms, error?` |
| `node.retry` | ✓ | `attempt, error` (read-only nodes only) |
| `approval.requested` | ✓ | `rule_id, reason, required_slots` |
| `approval.decided` | ✓ | `approval_id, decision, approver, approver_role, approval_status` |
| `node.awaiting_approval` / `node.completed` / `node.failed` / `node.rejected` / `node.skipped` | ✓ | `summary / error / reason, latency_ms` |
| `run.awaiting_approval` / `run.completed` / `run.failed` / `run.rejected` | | `error?` |

Events carry concise decision summaries and policy outcomes. Model reasoning is never stored or returned.

## Approval rules (enforced in `core/platform/approvals.py`)

* A step that policy marks `requires_human_approval` is **parked before execution**; an `approvals` row stores the exact parameter
  snapshot. That snapshot, not anything re-read later, is what executes after approval.
* Required approvals are *slots*, each with eligible roles: tier-2 = one of `manager|director|admin`; tier-3 = one `director` **and** one `controller`.
* The user who started the run can never decide it. Each person may decide once. A reject by any eligible approver ends the step.
* The slot is claimed by a unique database constraint and the approval transitions with a compare-and-set, so concurrent approvers
  cannot double-fill a slot or both resume the run.
* Resume claims the node with an atomic `awaiting_approval → running` update **before** calling the tool. A retried or duplicated
  resume therefore finds nothing to claim and does nothing: an approved side effect cannot repeat.
* If the process dies while a side-effecting node is `running`, recovery marks it `failed` ("Outcome unknown…") and never re-sends it.
  Read-only nodes are re-run.

## Audit

Every login, authorization denial, run start/finish, policy decision, tool execution, approval request/decision and workflow change is
appended to `audit_events`. Each row stores `sha256(prev_hash + canonical content)`; `GET /audit/verify` recomputes the chain.
Appends are serialised in-process. A multi-process deployment must serialise them in the database (e.g. an advisory lock).

## Agent runtime (added in v0.3)

The machine-readable contract is the OpenAPI document; this is the map. All routes are under `/api/v1`.

| Route | Permission | Purpose |
|---|---|---|
| `GET /agents`, `GET /agents/{id}`, `GET /agents/{id}/versions` | `registry:read` | The agent registry: hierarchy level, parent, tools, permissions, model, budgets, retry policy, status, version history |
| `POST /agents`, `PUT /agents/{id}` | `agent:write` (admin) | Create / edit. Every write is validated server-side and stored as a new immutable version. `422 {detail:{message, issues:[{code, message, field}]}}` lists every problem |
| `POST /agents/{id}/status` `{status}` | `agent:write` | `active` / `disabled` / `archived`. Refused while active children exist; an archived agent cannot be reactivated |
| `GET /tools` | `registry:read` | The tool registry: effect class (`read`/`write`/`destructive`), connector, roles, timeout, retries, JSON input schema |
| `GET /gateway/providers` | `registry:read` | Whether each model provider is reachable/configured. Never returns keys |
| `POST /plans` `{objective, mode, plan?}` | `workflow:run` | `mode`: `auto` (supervisor's model if configured, else deterministic), `deterministic`, `llm`, `structured` (you supply the plan). Returns the plan, every validation issue with its `category` (`planning_failure` / `policy_rejection` / `budget_exceeded`), the compiled workflow definition and the run-input fields. Persisted whether valid or not |
| `GET /plans/{id}` | `run:read` | Re-read a plan |
| `POST /plans/{id}/execute` `{inputs}` | `workflow:run` | Re-validates against the live registry and the caller's role, saves the compiled workflow, creates the run, returns `202`. `422` carries the issues if anything changed since planning |
| `POST /runs/{id}/cancel` | owner or `run:cancel_any` | `202`; `409` if already finished |
| `GET /runs/{id}/stream?after=N` | `run:read` | Server-Sent Events over the persisted event log (`event: run_event`, `id: <seq>`, final `event: end`). Resume with `after=` or `Last-Event-ID`. The fetch-based console client sends the bearer token; browsers' `EventSource` cannot, so there is also the polling feed below |
| `GET /runs/{id}/events?after=N` | `run:read` | Cursor-based polling feed (unchanged) |

Run and node statuses gained `partial` (run) and `cancelled`; approvals gained `cancelled`. `RunDetail` now carries `objective`, `plan_id`,
`budget`, `usage` (model tokens with `source = provider | estimated | mixed | none`; `cost_usd` is always null), `tool_calls_used` and, per
node, `delegation`, `agent_version`, `failure_class`, `usage`, `operations`, `evidence` and `criticality`.

### Event types (additions)

`plan.started`, `plan.completed`, `task.assigned`, `agent.delegated`, `model.call`, `tool.rejected` (arguments failed validation),
`tool.replayed` (a recorded result was reused instead of calling the tool), `node.retry` (with `delay_s`), `node.cancelled`,
`approval.cancelled`, `run.cancel_requested`, `run.cancelled`, `run.partial`. The earlier types are unchanged:
`run.created` (= workflow queued), `run.started/resumed`, `node.started/resumed/completed/failed/skipped/rejected`, `policy.decision`,
`tool.call`, `tool.result`, `approval.requested/decided`, `node.awaiting_approval`, `run.awaiting_approval/completed/failed/rejected`.
