"""Static validation of a workflow definition, run before saving-as-runnable and before execution."""
import re
from collections import defaultdict, deque
from typing import Any, Optional

from core.platform.catalog import CATALOG

REF = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
FIELD_TYPES = {"string", "number", "boolean"}


def refs_in(value: Any) -> list[str]:
    if isinstance(value, str):
        return [m.group(1) for m in REF.finditer(value)]
    if isinstance(value, dict):
        return [r for v in value.values() for r in refs_in(v)]
    if isinstance(value, list):
        return [r for v in value for r in refs_in(v)]
    return []


def topo_order(nodes: list[dict], edges: list[dict]) -> Optional[list[str]]:
    """Kahn's algorithm. Returns None if the graph has a cycle."""
    ids = [n["id"] for n in nodes]
    indeg = {i: 0 for i in ids}
    out = defaultdict(list)
    for e in edges:
        if e["source"] in indeg and e["target"] in indeg:
            out[e["source"]].append(e["target"])
            indeg[e["target"]] += 1
    queue = deque(i for i in ids if indeg[i] == 0)
    order = []
    while queue:
        cur = queue.popleft()
        order.append(cur)
        for nxt in out[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    return order if len(order) == len(ids) else None


def ancestors(node_id: str, edges: list[dict]) -> set[str]:
    parents = defaultdict(set)
    for e in edges:
        parents[e["target"]].add(e["source"])
    seen, stack = set(), [node_id]
    while stack:
        for p in parents[stack.pop()]:
            if p not in seen:
                seen.add(p)
                stack.append(p)
    return seen


def _issue(severity, code, message, node_id=None):
    return {"severity": severity, "code": code, "message": message, "node_id": node_id}


def trigger_fields(definition: dict) -> list[dict]:
    for n in definition.get("nodes", []):
        if n.get("type") == "trigger.manual":
            return list((n.get("params") or {}).get("fields") or [])
    return []


def _load_agents(db) -> dict:
    from core.platform import agent_registry
    return {a["id"]: a for a in agent_registry.list_agents(db, include_archived=True)}


def validate_definition(definition: dict, user_role: Optional[str] = None, agents: Optional[dict] = None,
                        db=None) -> list[dict]:
    """`db` is the caller's session (needed only when the workflow has agent tasks). Never opens its own:
    a nested session inside an open transaction would deadlock SQLite."""
    issues: list[dict] = []
    nodes = definition.get("nodes") or []
    edges = definition.get("edges") or []
    if agents is None and any(n.get("type") == "agent.task" for n in nodes):
        agents = _load_agents(db) if db is not None else {}

    if not nodes:
        return [_issue("error", "EMPTY", "The workflow has no nodes.")]

    ids = [n.get("id") for n in nodes]
    if len(set(ids)) != len(ids):
        issues.append(_issue("error", "DUPLICATE_ID", "Node IDs must be unique."))
    by_id = {n["id"]: n for n in nodes if n.get("id")}

    triggers = [n for n in nodes if n.get("type") == "trigger.manual"]
    if len(triggers) != 1:
        issues.append(_issue("error", "TRIGGER_COUNT", f"Exactly one manual trigger is required (found {len(triggers)})."))

    for n in nodes:
        spec = CATALOG.get(n.get("type"))
        if spec is None:
            issues.append(_issue("error", "UNKNOWN_NODE_TYPE", f"Unsupported node type '{n.get('type')}'.", n.get("id")))
            continue
        params = n.get("params") or {}
        if spec.kind == "trigger":
            seen = set()
            for f in params.get("fields") or []:
                name = f.get("name", "")
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
                    issues.append(_issue("error", "BAD_FIELD_NAME", f"Input field name '{name}' is not a valid identifier.", n["id"]))
                if name in seen:
                    issues.append(_issue("error", "DUPLICATE_FIELD", f"Input field '{name}' is declared twice.", n["id"]))
                seen.add(name)
                if f.get("type", "string") not in FIELD_TYPES:
                    issues.append(_issue("error", "BAD_FIELD_TYPE", f"Input field '{name}' has unsupported type.", n["id"]))
            continue
        for p in spec.params:
            raw = params.get(p.name, p.default)
            empty = raw is None or (isinstance(raw, str) and not raw.strip())
            if p.required and empty:
                issues.append(_issue("error", "MISSING_PARAM", f"'{p.label}' is required.", n["id"]))
                continue
            if empty:
                continue
            is_ref = isinstance(raw, str) and bool(REF.search(raw))
            if p.type == "json":
                if not isinstance(raw, (list, dict)):
                    issues.append(_issue("error", "BAD_PARAM_TYPE", f"'{p.label}' must be a JSON list or object.", n["id"]))
                continue
            if p.type == "number" and not is_ref:
                try:
                    float(raw)
                except (TypeError, ValueError):
                    issues.append(_issue("error", "BAD_PARAM_TYPE", f"'{p.label}' must be a number.", n["id"]))
            if p.type == "select" and not is_ref and raw not in p.options:
                issues.append(_issue("error", "BAD_PARAM_VALUE", f"'{p.label}' must be one of: {', '.join(p.options)}.", n["id"]))
        for ref in refs_in(params):
            parts = ref.split(".")
            if parts[0] == "trigger":
                names = {f.get("name") for f in trigger_fields(definition)}
                if len(parts) < 2 or parts[1] not in names:
                    issues.append(_issue("error", "UNKNOWN_REFERENCE", f"'{{{{{ref}}}}}' is not a declared trigger input.", n["id"]))
            elif parts[0] == "nodes" and len(parts) >= 3 and parts[2] == "output":
                src = by_id.get(parts[1])
                if src is None:
                    issues.append(_issue("error", "UNKNOWN_REFERENCE", f"'{{{{{ref}}}}}' points to a node that does not exist.", n["id"]))
                elif parts[1] not in ancestors(n["id"], edges):
                    issues.append(_issue("error", "REFERENCE_NOT_UPSTREAM",
                                         f"'{{{{{ref}}}}}' references '{parts[1]}', which is not upstream of this node.", n["id"]))
            else:
                issues.append(_issue("error", "BAD_REFERENCE",
                                     f"'{{{{{ref}}}}}' is not valid. Use trigger.<field> or nodes.<id>.output.<field>.", n["id"]))
        if spec.kind == "agent":
            from core.platform.planner import check_agent_task
            issues.extend(check_agent_task(params, agents or {}, user_role, n["id"]))
            continue
        if user_role and user_role not in spec.allowed_roles:
            issues.append(_issue("error", "ROLE_NOT_ALLOWED",
                                 f"Role '{user_role}' may not run '{spec.label}'.", n["id"]))

    edge_ids = set()
    for e in edges:
        if e.get("source") not in by_id or e.get("target") not in by_id:
            issues.append(_issue("error", "DANGLING_EDGE", "An edge connects to a node that does not exist."))
            continue
        if e["source"] == e["target"]:
            issues.append(_issue("error", "SELF_LOOP", "A node cannot connect to itself.", e["source"]))
        key = (e["source"], e["target"])
        if key in edge_ids:
            issues.append(_issue("warning", "DUPLICATE_EDGE", "Duplicate edge ignored.", e["source"]))
        edge_ids.add(key)
        if by_id[e["target"]].get("type") == "trigger.manual":
            issues.append(_issue("error", "TRIGGER_HAS_INPUT", "The trigger cannot have incoming edges.", e["target"]))

    if topo_order([n for n in nodes if n.get("id")], [e for e in edges if e.get("source") in by_id and e.get("target") in by_id]) is None:
        issues.append(_issue("error", "CYCLE", "The workflow contains a cycle."))
    elif len(triggers) == 1:
        reachable = {triggers[0]["id"]}
        changed = True
        while changed:
            changed = False
            for e in edges:
                if e.get("source") in reachable and e.get("target") not in reachable:
                    reachable.add(e["target"])
                    changed = True
        for n in nodes:
            if n.get("id") not in reachable:
                issues.append(_issue("error", "UNREACHABLE", "This node is not connected to the trigger.", n.get("id")))

    if agents and not has_errors(issues):
        from core.platform.planner import check_review_requirements
        issues.extend(check_review_requirements([n for n in nodes if n.get("id")], edges, agents))

    if len(nodes) == 1 and len(triggers) == 1:
        issues.append(_issue("warning", "NO_ACTIONS", "The workflow has a trigger but no action nodes."))
    return issues


def has_errors(issues: list[dict]) -> bool:
    return any(i["severity"] == "error" for i in issues)


def coerce_inputs(definition: dict, supplied: dict) -> tuple[dict, list[str]]:
    """Validate and coerce run inputs against the trigger's declared fields."""
    errors, result = [], {}
    fields = trigger_fields(definition)
    declared = {f["name"] for f in fields}
    for extra in set(supplied) - declared:
        errors.append(f"Unknown input '{extra}'.")
    for f in fields:
        name, ftype = f["name"], f.get("type", "string")
        raw = supplied.get(name, f.get("default"))
        if raw is None or raw == "":
            if f.get("required", True):
                errors.append(f"Input '{name}' is required.")
            continue
        try:
            if ftype == "number":
                result[name] = float(raw) if not isinstance(raw, bool) else (_ for _ in ()).throw(ValueError())
            elif ftype == "boolean":
                if isinstance(raw, bool):
                    result[name] = raw
                elif str(raw).lower() in ("true", "false"):
                    result[name] = str(raw).lower() == "true"
                else:
                    raise ValueError()
            else:
                result[name] = str(raw)
        except (ValueError, TypeError):
            errors.append(f"Input '{name}' must be a {ftype}.")
    return result, errors
