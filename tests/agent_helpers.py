"""Shared helpers for the agent-runtime tests: API calls, mock-system counters, temporary test tools."""
import threading
import time
import uuid
from contextlib import contextmanager

from core.platform import config, tools
from core.platform.tools import Strict, ToolResult, ToolSpec
from mock_systems.db import SessionLocal as MockSession
from mock_systems.models import Employee, ExpenseRecord, ITTicket

API = "/api/v1"
PW = config.dev_password()


def auth(client, username):
    r = client.post(f"{API}/auth/login", json={"username": username, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def mock_count(model):
    db = MockSession()
    try:
        return db.query(model).count()
    finally:
        db.close()


def expenses():
    return mock_count(ExpenseRecord)


def tickets():
    return mock_count(ITTicket)


def employees():
    return mock_count(Employee)


def detail(client, headers, run_id):
    r = client.get(f"{API}/runs/{run_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def node(d, node_id):
    return next(n for n in d["node_runs"] if n["node_id"] == node_id)


def events(client, headers, run_id):
    out, after = [], 0
    while True:
        page = client.get(f"{API}/runs/{run_id}/events", headers=headers, params={"after": after, "limit": 500}).json()
        out += page["events"]
        if not page["events"]:
            return out
        after = page["next_after"]


def types(evs):
    return [e["type"] for e in evs]


def make_plan(client, headers, objective, mode="deterministic", plan=None, expect=201):
    r = client.post(f"{API}/plans", headers=headers, json={"objective": objective, "mode": mode, **({"plan": plan} if plan else {})})
    assert r.status_code == expect, r.text
    return r.json()


def execute(client, headers, plan_id, inputs, expect=202):
    r = client.post(f"{API}/plans/{plan_id}/execute", headers=headers, json={"inputs": inputs})
    assert r.status_code == expect, r.text
    return r.json()


def expense_objective():
    return "Reimburse an expense claim with the receipt"


def expense_inputs(amount, emp="EMP-001"):
    return {"employee_id": emp, "amount": amount, "receipt_attached": True, "description": "Client dinner"}


def approve(client, headers, approval_id, decision="approve", expect=200):
    r = client.post(f"{API}/approvals/{approval_id}/decision", headers=headers, json={"decision": decision})
    assert r.status_code == expect, r.text
    return r.json()


def codes(issues):
    return {i["code"] for i in issues}


# ---------------------------------------------------------------- temporary tools
class NoArgs(Strict):
    tag: str = "x"


class Probe:
    """Counts calls and observes concurrency for a temporary test tool."""

    def __init__(self):
        self.calls, self.active, self.max_active, self.lock = 0, 0, 0, threading.Lock()
        self.fail_times, self.sleep_s, self.transient = 0, 0.0, True

    def handler(self, ctx, args):
        with self.lock:
            self.calls += 1
            n = self.calls
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.sleep_s:
                time.sleep(self.sleep_s)
            if n <= self.fail_times:
                if self.transient:
                    raise tools.TransientToolError("flaky upstream")
                return ToolResult(False, {}, "deterministic failure")
            return ToolResult(True, {"ok": True, "tag": args["tag"], "call": n}, evidence=[f"rec-{n}"])
        finally:
            with self.lock:
                self.active -= 1


@contextmanager
def temp_tool(name, effect="read", probe=None, **kw):
    probe = probe or Probe()
    spec = ToolSpec(name, f"test tool {name}", effect, ("testing",), NoArgs, probe.handler, "internal",
                    output_required=("ok",), **kw)
    tools.register(spec)
    try:
        yield probe
    finally:
        tools.unregister(name)


def new_agent_cfg(agent_id, tools_, parent="supervisor", level=1, **over):
    cfg = {"id": agent_id, "name": agent_id.replace("_", " ").title(), "level": level, "parent_id": parent,
           "capabilities": ["testing"], "allowed_tools": tools_,
           "permissions": {"read": True, "write": True, "destructive": over.pop("destructive", False)},
           "retry": {"max_retries": 2, "backoff_base_s": 0, "backoff_max_s": 0}}
    cfg.update(over)
    return cfg


def create_agent(client, admin, cfg):
    r = client.post(f"{API}/agents", headers=admin, json={"config": cfg})
    assert r.status_code == 201, r.text
    return r.json()


def uid(prefix="t"):
    return f"{prefix}_{uuid.uuid4().hex[:6]}"


def task(id, agent, ops, deps=(), **kw):
    return {"id": id, "description": f"Task {id}", "agent_id": agent, "depends_on": list(deps),
            "operations": [{"tool": t, "arguments": a} for t, a in ops], **kw}


def structured_plan(tasks, inputs=(), **constraints):
    return {"objective": "Test plan objective", "inputs": list(inputs), "tasks": tasks,
            **({"constraints": constraints} if constraints else {})}
