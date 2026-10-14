"""Agent runtime: registry, planning, scheduling, governance, approvals, durability, budgets, adversarial cases.

Real engine, real policy engine, real mock HRMS/ERP/ticketing. Deterministic: no network, no model,
except the ScriptedProvider that stands in for a model where a test needs model-driven behaviour."""
import threading
import time

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from core.platform import engine, gateway
from core.platform.db import session_factory
from core.platform.models import AuditEvent, NodeRun, Run, ToolExecution
from tests.agent_helpers import *  # noqa: F401,F403
from tests.agent_helpers import API, auth, codes, create_agent, detail, events, new_agent_cfg, node, types, uid


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin(client):
    return auth(client, "admin")


@pytest.fixture(scope="module")
def manager(client):
    return auth(client, "manager")


@pytest.fixture(autouse=True)
def _providers():
    yield
    gateway.reset_providers()


# ======================================================================== migrations
def test_migrations_upgrade_a_legacy_database_in_place(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    from core.platform import migrate
    eng = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    migrate.upgrade(eng, "0001")                      # the schema as it was before the agent runtime
    with eng.begin() as c:
        c.execute(text("INSERT INTO users (id, username, display_name, role, password_hash, active, created_at) "
                       "VALUES ('u1','u','U','admin','x',1,'2026-01-01')"))
        c.execute(text("INSERT INTO workflows (id,name,description,definition,version,created_by,created_at,updated_at) "
                       "VALUES ('w1','W','', '{}',1,'u1','2026-01-01','2026-01-01')"))
        c.execute(text("INSERT INTO runs (id,workflow_id,workflow_name,workflow_version,definition_snapshot,inputs,status,"
                       "started_by,started_by_role,created_at,next_seq) VALUES ('r1','w1','W',1,'{}','{}','completed','u1','admin','2026-01-01',1)"))
        c.execute(text("INSERT INTO approvals (id,run_id,node_id,status,risk_level,reason,tool_name,agent,params_snapshot,"
                       "required_slots,requested_by,requested_at) VALUES ('a1','r1','n','approved','low','r','t','finance','{}','[]','u1','2026-01-01')"))
        c.execute(text("INSERT INTO approval_decisions (approval_id,approver_id,approver_role,decision,slot_index,decided_at) "
                       "VALUES ('a1','u1','admin','approve',0,'2026-01-01')"))
    migrate.upgrade(eng)
    migrate.upgrade(eng)                              # idempotent
    insp = inspect(eng)
    assert {"agents", "agent_versions", "plans", "tool_executions"} <= set(insp.get_table_names())
    assert {"op_index", "evidence"} <= {c["name"] for c in insp.get_columns("approvals")}
    assert {"checkpoint", "usage", "failure_class"} <= {c["name"] for c in insp.get_columns("node_runs")}
    with eng.connect() as c:
        assert c.execute(text("SELECT status, op_index FROM approvals WHERE id='a1'")).one() == ("approved", 0)
        assert c.execute(text("SELECT count(*) FROM approval_decisions")).scalar() == 1
        assert c.execute(text("PRAGMA foreign_key_check")).fetchall() == []


# ======================================================================== registry
def test_builtin_hierarchy_is_seeded_and_levels_are_enforced(client, admin):
    agents = {a["id"]: a for a in client.get(f"{API}/agents", headers=admin).json()}
    assert agents["supervisor"]["level"] == 0 and agents["supervisor"]["tools"] == []
    assert agents["finance"]["level"] == 1 and agents["finance"]["parent"] == "supervisor"
    assert agents["expense_specialist"]["level"] == 2 and agents["expense_specialist"]["parent"] == "finance"
    assert set(agents["expense_specialist"]["tools"]) <= set(agents["finance"]["tools"])


def test_registry_rejects_invalid_configurations(client, admin):
    def bad(cfg, code, status=422):
        r = client.post(f"{API}/agents", headers=admin, json={"config": cfg})
        assert r.status_code == status, r.text
        assert code in {i["code"] for i in r.json()["detail"]["issues"]}, r.json()

    base = new_agent_cfg(uid("a"), ["hrms_get_employee"])
    bad({**base, "level": 0, "parent_id": None, "allowed_tools": ["hrms_get_employee"]}, "SUPERVISOR_TOOLS")
    bad({**base, "parent_id": "ghost"}, "UNKNOWN_PARENT")
    bad({**base, "allowed_tools": ["no_such_tool"]}, "UNKNOWN_TOOL")
    bad({**base, "allowed_tools": ["hrms_create_employee"], "permissions": {"read": True, "write": False, "destructive": False}},
        "PERMISSION_GAP")
    bad({**base, "level": 2, "parent_id": "supervisor"}, "BAD_HIERARCHY")
    bad({**base, "level": 2, "parent_id": "hr", "allowed_tools": ["erp_setup_payroll"]}, "EXCEEDS_PARENT")
    bad({**base, "id": "Bad Id"}, "SCHEMA")
    bad({**base, "output_schema": {"type": "object", "properties": {"x": {"$ref": "http://evil/schema"}}}}, "SCHEMA")
    bad({**base, "output_schema": {"type": "no-such-type"}}, "SCHEMA")
    bad({**base, "unexpected_field": "grant admin"}, "SCHEMA")           # config cannot smuggle extra keys
    bad({**base, "model": {"provider": "ollama"}}, "MODEL_MISSING")
    bad({**base, "id": "hr"}, "EXISTS", 409)


def test_agent_edits_create_versions_and_are_admin_only(client, admin, manager):
    aid = uid("ver")
    cfg = new_agent_cfg(aid, ["hrms_get_employee"])
    created = create_agent(client, admin, cfg)
    assert created["version"] == 1
    assert client.post(f"{API}/agents", headers=manager, json={"config": new_agent_cfg(uid("x"), [])}).status_code == 403
    assert client.put(f"{API}/agents/{aid}", headers=manager, json={"config": cfg}).status_code == 403
    r = client.put(f"{API}/agents/{aid}", headers=admin, json={"config": {**cfg, "description": "v2"}, "change_note": "docs"})
    assert r.status_code == 200 and r.json()["version"] == 2
    versions = client.get(f"{API}/agents/{aid}/versions", headers=admin).json()
    assert [v["version"] for v in versions] == [2, 1] and versions[1]["config"]["description"] == ""
    assert client.put(f"{API}/agents/{aid}", headers=admin, json={"config": {**cfg, "id": "other"}}).status_code in (200, 422)


def test_agent_lifecycle_and_hierarchy_integrity(client, admin):
    parent, child = uid("co"), uid("sp")
    create_agent(client, admin, new_agent_cfg(parent, ["hrms_get_employee", "rag_retrieve_policy"]))
    create_agent(client, admin, new_agent_cfg(child, ["hrms_get_employee"], parent=parent, level=2))
    # cannot disable a coordinator that still has an active specialist
    assert client.post(f"{API}/agents/{parent}/status", headers=admin, json={"status": "disabled"}).status_code == 409
    # cannot narrow the coordinator below what its specialist holds
    r = client.put(f"{API}/agents/{parent}", headers=admin, json={"config": new_agent_cfg(parent, ["rag_retrieve_policy"])})
    assert r.status_code == 409 and "CHILD_EXCEEDS" in {i["code"] for i in r.json()["detail"]["issues"]}
    assert client.post(f"{API}/agents/{child}/status", headers=admin, json={"status": "disabled"}).status_code == 200
    assert client.post(f"{API}/agents/{parent}/status", headers=admin, json={"status": "archived"}).status_code == 200
    assert client.post(f"{API}/agents/{parent}/status", headers=admin, json={"status": "active"}).status_code == 409
    # a cycle is impossible: the parent chain is validated on every write
    a, b = uid("ca"), uid("cb")
    create_agent(client, admin, new_agent_cfg(a, []))
    create_agent(client, admin, new_agent_cfg(b, [], parent=a, level=2))
    r = client.put(f"{API}/agents/{a}", headers=admin, json={"config": new_agent_cfg(a, [], parent=b, level=1)})
    assert r.status_code == 422 and {"BAD_HIERARCHY", "PARENT_CYCLE"} & {i["code"] for i in r.json()["detail"]["issues"]}


# ======================================================================== planning
def _issues(client, headers, plan_obj, expect_valid=False):
    p = make_plan_struct(client, headers, plan_obj)
    assert p["valid"] is expect_valid, p["issues"]
    return p


def make_plan_struct(client, headers, plan_obj):
    from tests.agent_helpers import make_plan
    return make_plan(client, headers, "Test plan objective", "structured", plan_obj)


def test_plan_validation_rejects_unknown_agents_edges_cycles_and_tools(client, manager):
    from tests.agent_helpers import structured_plan, task
    ok_op = [("rag_retrieve_policy", {"query": "expense policy"})]
    p = _issues(client, manager, structured_plan([task("a", "ghost_agent", ok_op)]))
    assert "UNKNOWN_AGENT" in codes(p["issues"]) and p["failure_category"] == "planning_failure"
    p = _issues(client, manager, structured_plan([task("a", "compliance_reviewer", ok_op, deps=["nope"])]))
    assert "UNKNOWN_DEPENDENCY" in codes(p["issues"])
    p = _issues(client, manager, structured_plan([task("a", "compliance_reviewer", ok_op, deps=["b"]),
                                                  task("b", "compliance_reviewer", ok_op, deps=["a"])]))
    assert "CYCLE" in codes(p["issues"])
    p = _issues(client, manager, structured_plan([task("a", "compliance_reviewer", [("no_such_tool", {})])]))
    assert "UNKNOWN_TOOL" in codes(p["issues"])
    p = _issues(client, manager, structured_plan([task("a", "compliance_reviewer", [("rag_retrieve_policy", {"query": "x"})])]))
    assert "BAD_ARGUMENTS" in codes(p["issues"])                      # min_length=3
    p = _issues(client, manager, structured_plan([task("a", "compliance_reviewer", [("rag_retrieve_policy", {"query": "policy", "evil": 1})])]))
    assert "BAD_ARGUMENTS" in codes(p["issues"])                      # unknown argument


def test_plan_validation_enforces_authority(client, manager):
    from tests.agent_helpers import structured_plan, task
    pay = ("erp_setup_payroll", {"employee_id": "EMP-001", "base_salary": 1000})
    # supervisor holds no tools and cannot be assigned business work
    p = _issues(client, manager, structured_plan([task("a", "supervisor", [("rag_retrieve_policy", {"query": "policy x"})])]))
    assert {"SUPERVISOR_TASK", "TOOL_NOT_ALLOWED"} <= codes(p["issues"]) and p["failure_category"] == "policy_rejection"
    # an agent may not use a tool outside its registry entry, even a real one
    p = _issues(client, manager, structured_plan([task("a", "expense_specialist", [pay])]))
    assert "TOOL_NOT_ALLOWED" in codes(p["issues"])
    # a read-only agent cannot be given a write operation
    p = _issues(client, manager, structured_plan([task("a", "compliance_reviewer", [pay])]))
    assert {"TOOL_NOT_ALLOWED", "EFFECT_NOT_PERMITTED"} <= codes(p["issues"])
    # role gate: an employee may not plan payroll
    emp = auth(client, "employee")
    p = _issues(client, emp, structured_plan([task("a", "payroll_specialist", [pay])]))
    assert "ROLE_NOT_ALLOWED" in codes(p["issues"])
    # the same plan is fine for a manager
    assert _issues(client, manager, structured_plan([task("a", "payroll_specialist", [pay])]), True)["status"] == "draft"
    # identical side-effecting call twice in one task is a duplicate-side-effect attempt
    p = _issues(client, manager, structured_plan([task("a", "payroll_specialist", [pay, pay])]))
    assert "DUPLICATE_SIDE_EFFECT" in codes(p["issues"])
    # missing capability
    p = _issues(client, manager, structured_plan([task("a", "payroll_specialist", [pay], required_capabilities=["wire_transfers"])]))
    assert "MISSING_CAPABILITY" in codes(p["issues"])


def test_a_plan_cannot_grant_itself_permissions_or_raise_limits(client, manager):
    from tests.agent_helpers import make_plan, structured_plan, task
    op = [("rag_retrieve_policy", {"query": "expense policy"})]
    evil = structured_plan([task("a", "compliance_reviewer", op)])
    evil["tasks"][0]["grant_permissions"] = ["destructive"]
    evil["policy_override"] = {"skip_approval": True}
    p = make_plan(client, manager, "Evil", "structured", evil)
    assert p["status"] == "invalid" and "MALFORMED_PLAN" in codes(p["issues"])
    p = _issues(client, manager, structured_plan([task("a", "compliance_reviewer", op)], max_tool_calls=100000, max_concurrency=500))
    assert "CONSTRAINT_ABOVE_CAP" in codes(p["issues"]) and p["failure_category"] == "policy_rejection"


def test_plan_resource_budgets_are_checked_before_execution(client, manager):
    from tests.agent_helpers import structured_plan, task
    op = ("rag_retrieve_policy", {"query": "expense policy"})
    p = _issues(client, manager, structured_plan([task("a", "compliance_reviewer", [op, op])], max_tool_calls=1))
    assert "PLAN_TOOL_BUDGET" in codes(p["issues"]) and p["failure_category"] == "budget_exceeded"
    p = _issues(client, manager, structured_plan([task(f"t{i}", "compliance_reviewer", [op]) for i in range(3)], max_tasks=2))
    assert "TOO_MANY_TASKS" in codes(p["issues"])


def test_review_requirement_demands_a_reviewer_downstream(client, admin, manager):
    from tests.agent_helpers import structured_plan, task
    aid = uid("rev")
    cfg = new_agent_cfg(aid, ["rag_retrieve_policy"], parent="finance", level=2, review={"required": True, "reviewer_agent_id": "compliance_reviewer"})
    cfg["permissions"] = {"read": True, "write": False, "destructive": False}
    create_agent(client, admin, cfg)
    op = [("rag_retrieve_policy", {"query": "expense policy"})]
    p = _issues(client, manager, structured_plan([task("a", aid, op)]))
    assert "REVIEW_MISSING" in codes(p["issues"])
    _issues(client, manager, structured_plan([task("a", aid, op), task("r", "compliance_reviewer", op, deps=["a"])]), True)


def test_unmatched_objective_is_a_planning_failure_not_a_guess(client, manager):
    from tests.agent_helpers import make_plan
    p = make_plan(client, manager, "Reorganize the quarterly sales offsite catering", "deterministic")
    assert p["status"] == "invalid" and p["failure_category"] == "planning_failure" and codes(p["issues"]) == {"NO_PLAYBOOK"}


# ======================================================================== model-backed planning
def _set_supervisor(client, admin, provider):
    cur = client.get(f"{API}/agents/supervisor", headers=admin).json()["config"]
    cur["model"] = {"provider": provider, "model": "", "tiers": {}, "temperature": 0, "max_output_tokens": 2048, "timeout_s": 30, "fallback": None}
    r = client.put(f"{API}/agents/supervisor", headers=admin, json={"config": cur, "change_note": f"test: {provider}"})
    assert r.status_code == 200, r.text


@pytest.fixture
def scripted_supervisor(client, admin):
    _set_supervisor(client, admin, "scripted")
    yield
    _set_supervisor(client, admin, "deterministic")


GOOD_PLAN = {"objective": "Look up the expense policy", "inputs": [], "tasks": [
    {"id": "p", "description": "Policy lookup", "agent_id": "compliance_reviewer",
     "operations": [{"tool": "rag_retrieve_policy", "arguments": {"query": "expense reimbursement approval"}}], "require_evidence": True}]}


def test_llm_planner_repairs_a_rejected_plan_within_a_bound(client, manager, scripted_supervisor):
    from tests.agent_helpers import make_plan
    bad = {**GOOD_PLAN, "tasks": [{**GOOD_PLAN["tasks"][0], "agent_id": "invented_agent"}]}
    provider = gateway.ScriptedProvider([bad, GOOD_PLAN])
    gateway.register_provider("scripted", provider)
    p = make_plan(client, manager, "Find the expense policy", "llm")
    assert p["valid"] and p["planner"] == "llm" and provider.calls == 2   # one rejection, one repair
    assert p["usage"]["calls"] == 2 and p["usage"]["source"] in ("provider", "estimated", "mixed")
    # the validation error (not the model's output) is what is fed back
    assert "UNKNOWN_AGENT" in provider.requests[1].messages[-1]["content"] or "invented_agent" in provider.requests[1].messages[-1]["content"]


def test_llm_planner_gives_up_after_the_repair_limit(client, manager, scripted_supervisor):
    from tests.agent_helpers import make_plan
    bad = {**GOOD_PLAN, "tasks": [{**GOOD_PLAN["tasks"][0], "agent_id": "invented_agent"}]}
    provider = gateway.ScriptedProvider([bad] * 10)
    gateway.register_provider("scripted", provider)
    p = make_plan(client, manager, "Find the expense policy", "llm")
    assert p["status"] == "invalid" and not p["valid"] and provider.calls == 3   # MAX_REPAIRS=2 -> 3 attempts, no more


def test_llm_plan_cannot_smuggle_permissions(client, manager, scripted_supervisor):
    from tests.agent_helpers import make_plan
    sneaky = {**GOOD_PLAN, "permissions": {"destructive": True}}
    gateway.register_provider("scripted", gateway.ScriptedProvider([sneaky, GOOD_PLAN]))
    p = make_plan(client, manager, "Find the expense policy", "llm")
    assert p["valid"]                       # the extra key was rejected by the schema, then repaired
    assert "permissions" not in p["plan"]


def test_auto_mode_falls_back_to_deterministic_when_the_model_is_down(client, manager, scripted_supervisor):
    from tests.agent_helpers import make_plan
    gateway.register_provider("scripted", gateway.ScriptedProvider([gateway.ProviderError("unavailable", "down")] * 5))
    p = make_plan(client, manager, "Reimburse an expense claim with the receipt", "auto")
    assert p["planner"] == "deterministic" and p["valid"] and "fell back" in (p["note"] or "")


# ======================================================================== gateway
import httpx  # noqa: E402


def _ollama(handler, **kw):
    return gateway.OllamaProvider("http://ollama.test", transport=httpx.MockTransport(handler), **kw)


REQ = gateway.ModelRequest("sys", [{"role": "user", "content": "hello"}], True, 64, 0, 5, "tiny-model")


def test_ollama_adapter_records_provider_reported_tokens():
    def handler(request):
        assert request.url.path == "/api/chat"
        return httpx.Response(200, json={"message": {"content": "{}"}, "prompt_eval_count": 11, "eval_count": 3})
    r = _ollama(handler).complete(REQ)
    assert (r.usage.input_tokens, r.usage.output_tokens, r.usage.source) == (11, 3, "provider")


def test_missing_usage_is_labelled_estimated_never_fabricated_as_real():
    r = _ollama(lambda req: httpx.Response(200, json={"message": {"content": "{\"a\":1}"}})).complete(REQ)
    assert r.usage.source == "estimated" and r.usage.provider_reported_calls == 0 and r.usage.to_dict()["cost_usd"] is None


def test_openai_compatible_adapter_and_error_mapping():
    ok = gateway.OpenAICompatProvider("http://x.test", "k", httpx.MockTransport(lambda r: httpx.Response(
        200, json={"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 7, "completion_tokens": 2}})))
    assert ok.complete(REQ).usage.source == "provider"
    for status, kind in ((401, "auth"), (500, "unavailable"), (429, "rate_limited"), (400, "http_error")):
        p = gateway.OpenAICompatProvider("http://x.test", "k", httpx.MockTransport(lambda r, s=status: httpx.Response(s)))
        with pytest.raises(gateway.ProviderError) as e:
            p.complete(REQ)
        assert e.value.kind == kind
    with pytest.raises(gateway.ProviderError) as e:
        gateway.OpenAICompatProvider("", "").complete(REQ)
    assert e.value.kind == "not_configured"


def test_gateway_handles_rate_limits_timeouts_fallback_and_budgets():
    calls, sleeps = [], []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "1"})
        return httpx.Response(200, json={"message": {"content": "{}"}, "prompt_eval_count": 5, "eval_count": 1})
    gateway.register_provider("ollama", _ollama(handler))
    gw = gateway.Gateway({"provider": "ollama", "model": "m"}, sleep=sleeps.append)
    gw.complete(REQ)
    assert len(calls) == 2 and sleeps == [1.0]                                   # honoured retry-after, once
    # timeout -> classified; fallback provider takes over
    def slow(request):
        raise httpx.ReadTimeout("slow")
    gateway.register_provider("ollama", _ollama(slow))
    gateway.register_provider("scripted", gateway.ScriptedProvider(["{}"]))
    gw = gateway.Gateway({"provider": "ollama", "model": "m", "fallback": {"provider": "scripted", "model": "s"}})
    assert gw.complete(REQ).provider == "scripted"
    with pytest.raises(gateway.ProviderError) as e:
        gateway.Gateway({"provider": "ollama", "model": "m"}).complete(REQ)
    assert e.value.kind == "timeout"
    # budgets: call count and tokens
    gateway.register_provider("scripted", gateway.ScriptedProvider(lambda r, i: "{}"))
    gw = gateway.Gateway({"provider": "scripted"}, max_calls=2)
    gw.complete(REQ); gw.complete(REQ)
    with pytest.raises(gateway.BudgetExceeded):
        gw.complete(REQ)
    with pytest.raises(gateway.BudgetExceeded):
        big = gateway.ModelRequest("x" * 400, [{"role": "user", "content": "hello"}], True, 64, 0, 5, "m")
        gateway.Gateway({"provider": "scripted"}, max_total_tokens=50).complete(big)   # ~100 tokens needed


def test_model_tier_selection_follows_task_complexity():
    cfg = {"model": "default-m", "tiers": {"small": "tiny", "large": "big"}}
    assert gateway.select_model(cfg, "low") == "tiny"
    assert gateway.select_model(cfg, "medium") == "default-m"
    assert gateway.select_model(cfg, "high") == "big"
    assert gateway.select_model({"model": "only"}, "high") == "only"


def test_structured_output_is_validated_with_bounded_repair():
    from pydantic import BaseModel

    class Out(BaseModel):
        n: int
    gateway.register_provider("scripted", gateway.ScriptedProvider(['{"n": "x"}', "```json\n{\"n\": 4}\n```"]))
    assert gateway.Gateway({"provider": "scripted"}).complete_structured(REQ, Out, max_repairs=1).n == 4
    gateway.register_provider("scripted", gateway.ScriptedProvider(["nope", "still nope", "{\"n\":1}"]))
    with pytest.raises(gateway.ProviderError) as e:
        gateway.Gateway({"provider": "scripted"}).complete_structured(REQ, Out, max_repairs=1)
    assert e.value.kind == "bad_response"


# ======================================================================== redaction
def test_redaction_masks_credentials_but_keeps_token_counts():
    from core.platform.redaction import redact_secrets as r
    out = r({"input_tokens": 5, "max_total_tokens": 9, "access_token": "x", "api_key": "k", "password": "p",
             "nested": {"output_tokens": 1, "refresh_token": "z"}, "Authorization": "Bearer abc"})
    assert out["input_tokens"] == 5 and out["max_total_tokens"] == 9 and out["nested"]["output_tokens"] == 1
    assert {out["access_token"], out["api_key"], out["password"], out["Authorization"], out["nested"]["refresh_token"]} == {"[REDACTED]"}
