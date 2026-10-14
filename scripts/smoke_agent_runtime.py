"""End-to-end smoke test against a RUNNING API (async workers, real HTTP, real SSE).

    python -m uvicorn apps.api.main:app --port 8000
    python scripts/smoke_agent_runtime.py http://127.0.0.1:8000

Plans an expense reimbursement, executes it, watches the live event stream, approves as a director,
and checks the run completed with the full persisted trace. Exits non-zero on any failed expectation."""
import json
import os
import sys
import threading
import time

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
PW = os.getenv("HACFEW_DEV_PASSWORD", "hacfew-dev")
api = httpx.Client(base_url=BASE + "/api/v1", timeout=30)


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        sys.exit(1)


def login(user):
    r = api.post("/auth/login", json={"username": user, "password": PW})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def wait(pred, what, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.3)
    check(False, f"timed out waiting for {what}")


for _ in range(60):
    try:
        if httpx.get(BASE + "/health", timeout=2).status_code == 200:
            break
    except httpx.HTTPError:
        time.sleep(1)
else:
    check(False, "API did not become healthy")

mgr, director = login("manager"), login("director")
agents = api.get("/agents", headers=mgr).json()
check({a["level"] for a in agents} == {0, 1, 2}, f"agent hierarchy seeded ({len(agents)} agents, levels 0-2)")

plan = api.post("/plans", headers=mgr, json={"objective": "Reimburse an expense claim with the receipt", "mode": "auto"}).json()
check(plan["valid"], f"plan valid (planner={plan['planner']}, tasks={len(plan['plan']['tasks'])})")
run = api.post(f"/plans/{plan['id']}/execute", headers=mgr, json={"inputs": {
    "employee_id": "EMP-001", "amount": 350, "receipt_attached": True, "description": "smoke test"}}).json()
rid = run["id"]

seen: list[dict] = []


def listen():
    with httpx.stream("GET", f"{BASE}/api/v1/runs/{rid}/stream", headers=mgr, timeout=60) as r:
        ev = {}
        for line in r.iter_lines():
            if line.startswith(("id:", "event:", "data:")):
                k, v = line.split(":", 1)
                ev[k] = v.strip()
            elif not line and ev:
                seen.append(ev)
                ev = {}


threading.Thread(target=listen, daemon=True).start()
d = wait(lambda: (lambda x: x if x["status"] == "awaiting_approval" else None)(api.get(f"/runs/{rid}", headers=mgr).json()),
         "run to pause for approval")
check(d["approvals"][0]["tool_name"] == "erp_submit_expense", "run paused on the protected operation (worker thread, not the HTTP request)")
wait(lambda: any(e.get("event") == "run_event" for e in seen), "live SSE events while paused", 10)
check(True, f"live SSE events received while paused ({len(seen)})")
r = api.post(f"/approvals/{d['approvals'][0]['id']}/decision", headers=director, json={"decision": "approve"})
check(r.status_code == 200, "director approved")
d = wait(lambda: (lambda x: x if x["status"] in ("completed", "failed", "rejected", "cancelled", "partial") else None)(
    api.get(f"/runs/{rid}", headers=mgr).json()), "run to finish")
check(d["status"] == "completed", f"run completed ({[(n['node_id'], n['status']) for n in d['node_runs']]})")
wait(lambda: any(e.get("event") == "end" for e in seen), "SSE end event")
persisted = api.get(f"/runs/{rid}/events", headers=mgr, params={"limit": 500}).json()["events"]
streamed = [json.loads(e["data"])["seq"] for e in seen if e.get("event") == "run_event"]
check(streamed == [e["seq"] for e in persisted], f"stream == persisted log ({len(persisted)} events)")
print("SMOKE PASSED")
