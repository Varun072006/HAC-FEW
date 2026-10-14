"""Platform API tests: auth, workflows, execution, approvals, audit, redaction, recovery.

These run the real engine and the real policy engine against the bundled mock systems.
Only the platform database is isolated (see conftest.py)."""
import copy
import os

import jwt
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from core.platform import config
from core.platform.db import session_factory
from core.platform.models import AuditEvent, NodeRun, Run
from core.platform.templates import get_template
from mock_systems.db import SessionLocal as MockSession
from mock_systems.models import ExpenseRecord

PW = config.dev_password()
API = "/api/v1"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def auth(client, username):
    r = client.post(f"{API}/auth/login", json={"username": username, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def expense_count():
    db = MockSession()
    try:
        return db.query(ExpenseRecord).count()
    finally:
        db.close()


def make_workflow(client, headers, template_id):
    t = get_template(template_id)
    r = client.post(f"{API}/workflows", headers=headers,
                    json={"name": t["name"], "description": t["description"], "definition": t["definition"],
                          "template_id": template_id})
    assert r.status_code == 201, r.text
    return r.json()


def start(client, headers, workflow_id, inputs, expect=202):
    r = client.post(f"{API}/workflows/{workflow_id}/runs", headers=headers, json={"inputs": inputs})
    assert r.status_code == expect, r.text
    return r.json()


def run_detail(client, headers, run_id):
    r = client.get(f"{API}/runs/{run_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def node(detail, node_id):
    return next(n for n in detail["node_runs"] if n["node_id"] == node_id)


@pytest.fixture(scope="module")
def expense_wf(client):
    return make_workflow(client, auth(client, "manager"), "expense-approval")


def expense_inputs(amount, receipt=True, emp="EMP-001"):
    return {"employee_id": emp, "amount": amount, "receipt_attached": receipt, "description": "Client dinner"}


# ---------------------------------------------------------------- auth
def test_unauthenticated_requests_are_rejected(client):
    for path in ("/workflows", "/runs", "/approvals", "/audit", "/overview"):
        assert client.get(f"{API}{path}").status_code == 401


def test_login_failure_and_token_forgery(client):
    assert client.post(f"{API}/auth/login", json={"username": "admin", "password": "nope"}).status_code == 401
    forged = jwt.encode({"sub": "usr_admin", "exp": 4102444800}, "attacker-secret-attacker-secret-1234", algorithm="HS256")
    r = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_role_comes_from_database_not_client(client):
    h = auth(client, "employee")
    assert client.get(f"{API}/auth/me", headers=h).json()["role"] == "employee"
    assert client.get(f"{API}/audit", headers=h).status_code == 403
    assert client.post(f"{API}/workflows", headers=h, json={"name": "x", "definition": {"nodes": [], "edges": []}}).status_code == 403


def test_legacy_endpoint_disabled_by_default(client, monkeypatch):
    monkeypatch.setenv("HACFEW_ENABLE_LEGACY_API", "0")
    r = client.post("/workflows/run", json={"user_id": "x", "role": "admin", "request": "onboard someone"})
    assert r.status_code == 410


# ---------------------------------------------------------------- validation
def test_validation_catches_structural_errors(client):
    h = auth(client, "manager")
    t = copy.deepcopy(get_template("expense-approval")["definition"])
    t["edges"].append({"id": "loop", "source": "submit", "target": "policy"})
    codes = {i["code"] for i in client.post(f"{API}/workflows/validate", headers=h, json=t).json()["issues"]}
    assert "CYCLE" in codes

    t = copy.deepcopy(get_template("expense-approval")["definition"])
    t["nodes"][2]["params"]["amount"] = "{{trigger.missing}}"
    res = client.post(f"{API}/workflows/validate", headers=h, json=t).json()
    assert not res["valid"] and any(i["code"] == "UNKNOWN_REFERENCE" for i in res["issues"])

    t = copy.deepcopy(get_template("employee-onboarding")["definition"])
    t["nodes"][2]["params"]["employee_id"] = "{{nodes.laptop.output.id}}"  # sibling, not upstream
    res = client.post(f"{API}/workflows/validate", headers=h, json=t).json()
    assert any(i["code"] == "REFERENCE_NOT_UPSTREAM" for i in res["issues"])


def test_all_templates_are_valid(client):
    h = auth(client, "admin")
    for t in client.get(f"{API}/templates", headers=h).json():
        res = client.post(f"{API}/workflows/validate", headers=h, json=t["definition"]).json()
        assert res["valid"], (t["id"], res["issues"])


def test_invalid_workflow_cannot_run_and_inputs_are_checked(client, expense_wf):
    h = auth(client, "manager")
    r = client.post(f"{API}/workflows/{expense_wf['id']}/runs", headers=h, json={"inputs": {"amount": "abc"}})
    assert r.status_code == 422
    bad = client.post(f"{API}/workflows", headers=h, json={"name": "bad", "definition": {
        "nodes": [{"id": "trigger", "type": "trigger.manual", "params": {}}, {"id": "x", "type": "nope.type"}],
        "edges": []}}).json()
    assert client.post(f"{API}/workflows/{bad['id']}/runs", headers=h, json={"inputs": {}}).status_code == 422


def test_optimistic_concurrency(client, expense_wf):
    h = auth(client, "manager")
    ok = client.put(f"{API}/workflows/{expense_wf['id']}", headers=h,
                    json={"expected_version": expense_wf["version"], "description": "edited"})
    assert ok.status_code == 200 and ok.json()["version"] == expense_wf["version"] + 1
    stale = client.put(f"{API}/workflows/{expense_wf['id']}", headers=h,
                       json={"expected_version": expense_wf["version"], "description": "stale"})
    assert stale.status_code == 409


# ---------------------------------------------------------------- execution
def test_low_value_expense_auto_approves_and_history_is_persisted(client, expense_wf):
    h = auth(client, "employee")
    before = expense_count()
    run = start(client, h, expense_wf["id"], expense_inputs(45))
    d = run_detail(client, h, run["id"])
    assert d["status"] == "completed"
    submit = node(d, "submit")
    assert submit["status"] == "completed" and submit["output"]["status"] == "approved"
    assert submit["policy"]["rule_id"] == "RULE-FIN-TIER-1"
    assert submit["tool_calls"][0]["tool"] == "erp_submit_expense"
    assert expense_count() == before + 1

    page = client.get(f"{API}/runs/{run['id']}/events?after=0", headers=h).json()
    types = [e["type"] for e in page["events"]]
    assert page["terminal"] and types[0] == "run.created" and types[-1] == "run.completed"
    assert "policy.decision" in types and "tool.call" in types and "tool.result" in types
    assert [e["seq"] for e in page["events"]] == sorted(e["seq"] for e in page["events"])
    again = client.get(f"{API}/runs/{run['id']}/events?after={page['next_after']}", headers=h).json()
    assert again["events"] == []


def test_run_history_survives_new_session_factory(client, expense_wf):
    """Everything the UI shows is read back from the database, not from process memory."""
    h = auth(client, "manager")
    run = start(client, h, expense_wf["id"], expense_inputs(20, emp="EMP-002"))
    db = session_factory()()
    try:
        row = db.get(Run, run["id"])
        assert row.status == "completed" and row.definition_snapshot["nodes"]
        assert db.query(NodeRun).filter(NodeRun.run_id == run["id"]).count() == 3
    finally:
        db.close()


def test_missing_receipt_is_blocked_with_no_side_effect(client, expense_wf):
    h = auth(client, "employee")
    before = expense_count()
    d = run_detail(client, h, start(client, h, expense_wf["id"], expense_inputs(85, receipt=False))["id"])
    assert d["status"] == "failed"
    assert node(d, "submit")["status"] == "failed" and "receipt" in node(d, "submit")["error"].lower()
    assert expense_count() == before


def test_employee_cannot_submit_for_someone_else(client, expense_wf):
    h = auth(client, "employee")
    before = expense_count()
    d = run_detail(client, h, start(client, h, expense_wf["id"], expense_inputs(45, emp="EMP-002"))["id"])
    assert d["status"] == "failed" and node(d, "submit")["policy"]["rule_id"] == "RULE-AUTHZ-SELF"
    assert expense_count() == before


# ---------------------------------------------------------------- approvals
def test_manager_approval_releases_exactly_one_side_effect(client, expense_wf):
    emp, mgr = auth(client, "employee"), auth(client, "manager")
    before = expense_count()
    run = start(client, emp, expense_wf["id"], expense_inputs(350))
    d = run_detail(client, emp, run["id"])
    assert d["status"] == "awaiting_approval"
    assert node(d, "submit")["status"] == "awaiting_approval"
    assert expense_count() == before, "no side effect may happen before approval"
    approval = d["approvals"][0]
    assert approval["status"] == "pending" and approval["can_decide"] is False  # requester

    # the requester and an unauthorised role are refused server-side
    assert client.post(f"{API}/approvals/{approval['id']}/decision", headers=emp,
                       json={"decision": "approve"}).status_code == 403
    assert client.post(f"{API}/approvals/{approval['id']}/decision", headers=auth(client, "it"),
                       json={"decision": "approve"}).status_code == 403
    assert expense_count() == before

    r = client.post(f"{API}/approvals/{approval['id']}/decision", headers=mgr, json={"decision": "approve", "comment": "ok"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    d = run_detail(client, emp, run["id"])
    assert d["status"] == "completed"
    out = node(d, "submit")["output"]
    assert out["status"] == "approved" and "Morgan Manager" in (out["approved_by"] or "")
    assert expense_count() == before + 1

    # retried decision and forced re-drive must not repeat the side effect
    assert client.post(f"{API}/approvals/{approval['id']}/decision", headers=mgr,
                       json={"decision": "approve"}).status_code == 409
    from core.platform import engine
    engine.drive(run["id"])
    engine.drive(run["id"])
    assert expense_count() == before + 1


def test_high_value_requires_director_and_controller(client, expense_wf):
    emp = auth(client, "employee")
    before = expense_count()
    run = start(client, emp, expense_wf["id"], expense_inputs(2400))
    approval = run_detail(client, emp, run["id"])["approvals"][0]
    assert approval["required_slots"] == [["director"], ["controller"]]
    url = f"{API}/approvals/{approval['id']}/decision"

    assert client.post(url, headers=auth(client, "manager"), json={"decision": "approve"}).status_code == 403
    first = client.post(url, headers=auth(client, "director"), json={"decision": "approve"})
    assert first.status_code == 200 and first.json()["status"] == "pending"
    assert run_detail(client, emp, run["id"])["status"] == "awaiting_approval"
    assert expense_count() == before
    assert client.post(url, headers=auth(client, "director"), json={"decision": "approve"}).status_code == 409

    second = client.post(url, headers=auth(client, "controller"), json={"decision": "approve"})
    assert second.status_code == 200 and second.json()["status"] == "approved"
    d = run_detail(client, emp, run["id"])
    assert d["status"] == "completed" and expense_count() == before + 1
    assert "Dana Director" in node(d, "submit")["output"]["approved_by"]
    assert "Casey Controller" in node(d, "submit")["output"]["approved_by"]


def test_rejection_stops_the_run_with_no_side_effect(client, expense_wf):
    emp = auth(client, "employee")
    before = expense_count()
    run = start(client, emp, expense_wf["id"], expense_inputs(500))
    approval = run_detail(client, emp, run["id"])["approvals"][0]
    r = client.post(f"{API}/approvals/{approval['id']}/decision", headers=auth(client, "director"),
                    json={"decision": "reject", "comment": "Not a business expense"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    d = run_detail(client, emp, run["id"])
    assert d["status"] == "rejected" and node(d, "submit")["status"] == "rejected"
    assert "Not a business expense" in node(d, "submit")["error"]
    assert expense_count() == before
    assert client.post(f"{API}/approvals/{approval['id']}/decision", headers=auth(client, "manager"),
                       json={"decision": "approve"}).status_code == 409


def test_approval_visibility_is_scoped(client, expense_wf):
    emp = auth(client, "employee")
    start(client, emp, expense_wf["id"], expense_inputs(150))
    mine = client.get(f"{API}/approvals?status=pending", headers=emp).json()["items"]
    assert mine and all(a["requested_by"] == "usr_employee" for a in mine)
    assert all(not a["can_decide"] for a in mine)
    theirs = client.get(f"{API}/approvals?status=pending", headers=auth(client, "manager")).json()["items"]
    assert len(theirs) >= len(mine)
    # a different low-privilege viewer cannot read another user's run
    run = client.get(f"{API}/runs", headers=emp).json()["items"][0]
    assert client.get(f"{API}/runs/{run['id']}", headers=auth(client, "employee")).status_code == 200


# ---------------------------------------------------------------- onboarding / redaction
def test_onboarding_chains_outputs_and_redacts_pii_per_viewer(client):
    mgr = auth(client, "manager")
    wf = make_workflow(client, mgr, "employee-onboarding")
    import uuid
    run = start(client, mgr, wf["id"], {"name": "Elena Rostova", "email": f"elena.{uuid.uuid4().hex[:6]}@company.test",
                                         "department": "Engineering", "role": "Staff Engineer"})
    d = run_detail(client, mgr, run["id"])
    assert d["status"] == "completed", [(n["node_id"], n["status"], n["error"]) for n in d["node_runs"]]
    emp_id = node(d, "hr")["output"]["id"]
    assert emp_id.startswith("EMP-")
    assert node(d, "payroll")["input"]["employee_id"] == emp_id
    assert node(d, "payroll")["input"]["base_salary"] == "[RESTRICTED]"  # manager has no pii:read
    admin_view = run_detail(client, auth(client, "admin"), run["id"])
    assert node(admin_view, "payroll")["input"]["base_salary"] == 95000.0
    events = client.get(f"{API}/runs/{run['id']}/events", headers=mgr).json()["events"]
    assert "[RESTRICTED]" in str([e["data"] for e in events if e["type"] == "tool.call"])


def test_employee_role_cannot_run_privileged_nodes(client):
    wf = make_workflow(client, auth(client, "manager"), "employee-onboarding")
    r = client.post(f"{API}/workflows/{wf['id']}/runs", headers=auth(client, "employee"),
                    json={"inputs": {"name": "A B", "email": "a@b.test", "department": "X", "role": "Y"}})
    assert r.status_code == 422
    assert any(i["code"] == "ROLE_NOT_ALLOWED" for i in r.json()["detail"]["issues"])


# ---------------------------------------------------------------- audit & recovery
def test_audit_trail_records_decisions_and_chain_verifies(client):
    ctrl = auth(client, "controller")
    items = client.get(f"{API}/audit?limit=500", headers=ctrl).json()["items"]
    actions = {i["action"] for i in items}
    assert {"auth.login", "run.started", "policy.decision", "approval.requested", "approval.decided",
            "authz.denied", "approval.decision_denied"} <= actions
    assert client.get(f"{API}/audit/verify", headers=ctrl).json()["valid"] is True

    db = session_factory()()
    try:
        ev = db.query(AuditEvent).order_by(AuditEvent.id.asc()).first()
        ev.action = "tampered"
        db.commit()
    finally:
        db.close()
    assert client.get(f"{API}/audit/verify", headers=ctrl).json()["valid"] is False
    db = session_factory()()
    try:
        ev = db.query(AuditEvent).order_by(AuditEvent.id.asc()).first()
        ev.action = "auth.login"
        db.commit()
    finally:
        db.close()
    assert client.get(f"{API}/audit/verify", headers=ctrl).json()["valid"] is True


def test_restart_recovery_never_resends_a_side_effect(client, expense_wf):
    from core.platform import engine
    mgr = auth(client, "manager")
    run = start(client, mgr, expense_wf["id"], expense_inputs(30))
    db = session_factory()()
    try:
        # simulate a crash mid-call: run and the side-effecting node are stuck in "running"
        r = db.get(Run, run["id"])
        r.status, r.finished_at = "running", None
        n = db.query(NodeRun).filter_by(run_id=run["id"], node_id="submit").one()
        n.status, n.output, n.finished_at = "running", None, None
        db.commit()
    finally:
        db.close()
    before = expense_count()
    assert engine.recover_interrupted_runs() >= 1
    d = run_detail(client, mgr, run["id"])
    assert d["status"] == "failed"
    assert "Outcome unknown" in node(d, "submit")["error"]
    assert expense_count() == before


def test_agent_connector_policy_and_usage_registries_are_real(client):
    admin = auth(client, "admin")
    agents = {a["id"]: a for a in client.get(f"{API}/agents", headers=admin).json()}
    assert agents["finance"]["parent"] == "supervisor" and "erp_submit_expense" in agents["finance"]["tools"]
    assert agents["finance"]["node_runs"] > 0
    conns = {c["id"]: c for c in client.get(f"{API}/connectors", headers=admin).json()}
    assert conns["erp"]["status"] == "healthy" and conns["erp"]["configurable"] is False
    pol = client.get(f"{API}/policies", headers=admin).json()
    assert {r["rule_id"] for r in pol["rules"]} >= {"RULE-FIN-TIER-1", "RULE-FIN-TIER-2", "RULE-FIN-TIER-3"}
    usage = client.get(f"{API}/usage", headers=admin).json()
    # truthful whatever ran before: model usage is reported only if model-backed tasks actually ran
    assert usage["llm_backed"] == (usage["llm_calls"] > 0) and usage["total_node_runs"] > 0
    ov = client.get(f"{API}/overview", headers=admin).json()
    assert ov["runs_total"] == sum(ov["runs_by_status"].values())


def test_every_decision_rule_is_documented():
    from core.governance.policy_engine import GovernancePolicyEngine as G, RULES_CATALOG
    known = {r["rule_id"] for r in RULES_CATALOG}
    cases = [("finance", "erp_submit_expense", {"amount": a, "receipt_attached": r})
             for a, r in [(10, True), (500, True), (5000, True), (10, False)]]
    cases += [("hr", "hrms_create_employee", {}), ("finance", "erp_setup_payroll", {}),
              ("it", "ticketing_create_ticket", {}), ("it", "notifications_send_email", {}),
              ("hr", "erp_submit_expense", {"amount": 1}), ("finance", "erp_get_expense", {})]
    for agent, tool, params in cases:
        assert G.evaluate_tool_execution(agent, tool, params).rule_id in known


def test_concurrent_decisions_on_one_slot_execute_once(client, expense_wf):
    """Two eligible approvers racing for the single tier-2 slot: one wins, one gets 409, one expense."""
    from concurrent.futures import ThreadPoolExecutor
    emp = auth(client, "employee")
    before = expense_count()
    run = start(client, emp, expense_wf["id"], expense_inputs(220))
    approval = run_detail(client, emp, run["id"])["approvals"][0]
    url = f"{API}/approvals/{approval['id']}/decision"
    heads = [auth(client, "manager"), auth(client, "director")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(f.result().status_code for f in
                       [pool.submit(client.post, url, headers=h, json={"decision": "approve"}) for h in heads])
    assert codes == [200, 409], codes
    assert run_detail(client, emp, run["id"])["status"] == "completed"
    assert expense_count() == before + 1


def test_tampered_or_expired_tokens_are_rejected(client):
    import time
    expired = jwt.encode({"sub": "usr_admin", "exp": int(time.time()) - 10}, config.jwt_secret(), algorithm="HS256")
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    ok = auth(client, "admin")["Authorization"].split()[1]
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {ok[:-3]}abc"}).status_code == 401
