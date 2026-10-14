"""Static, type-specific checks run by the workflow validator before anything is saved as runnable or executed.
They only ever look at the definition (never at data), so the same checks run in the editor, on save and at run start."""
import re
from typing import Callable

from core.automation.analysis import AuditRules
from core.automation.validation import parse_schema
from core.connectors.email import ADDRESS, MAX_RECIPIENTS
from core.platform.security import ROLES, permissions_for
from core.platform.validation import REF, ancestors, refs_in

Issue = tuple[str, str, str]   # (severity, code, message)


def _is_ref(v) -> bool:
    return isinstance(v, str) and bool(REF.search(v))


def _has_ref(v) -> bool:
    return bool(refs_in(v))


def check_condition(node: dict, definition: dict) -> list[Issue]:
    out_edges = [e for e in definition["edges"] if e["source"] == node["id"]]
    issues: list[Issue] = []
    if not out_edges:
        issues.append(("warning", "NO_BRANCHES", "This condition has no outgoing connections, so both branches end here."))
    for e in out_edges:
        if e.get("branch") not in ("true", "false"):
            issues.append(("error", "BRANCH_REQUIRED", f"The connection to '{e['target']}' must be labelled as the true or false branch."))
    seen = set()
    for e in out_edges:
        k = (e["target"], e.get("branch"))
        if k in seen:
            issues.append(("error", "DUPLICATE_BRANCH", f"'{e['target']}' is connected to the same branch twice."))
        seen.add(k)
    return issues


def check_approval(node: dict, definition: dict) -> list[Issue]:
    roles = (node.get("params") or {}).get("approver_roles")
    if roles is None:
        return []
    if not isinstance(roles, list) or not roles or not all(isinstance(g, list) and g and all(isinstance(r, str) for r in g) for g in roles):
        return [("error", "BAD_APPROVER_ROLES", "Approver roles must be a non-empty list of non-empty role lists, e.g. [[\"director\"],[\"controller\"]].")]
    issues: list[Issue] = []
    for g in roles:
        for r in g:
            if r not in ROLES:
                issues.append(("error", "UNKNOWN_ROLE", f"'{r}' is not a role in this organization."))
            elif "approval:decide" not in permissions_for(r):
                issues.append(("error", "ROLE_CANNOT_APPROVE", f"Role '{r}' has no permission to decide approvals, so this gate could never complete."))
    return issues


def check_validate(node: dict, definition: dict) -> list[Issue]:
    schema = (node.get("params") or {}).get("schema")
    if isinstance(schema, dict) and not _has_ref(schema):
        try:
            parse_schema(schema)
        except ValueError as exc:
            return [("error", "BAD_SCHEMA", f"The validation schema is invalid: {exc}")]
    return []


def check_analyze(node: dict, definition: dict) -> list[Issue]:
    rules = (node.get("params") or {}).get("rules")
    if isinstance(rules, dict) and not _has_ref(rules):
        try:
            AuditRules.model_validate(rules)
        except ValueError as exc:
            return [("error", "BAD_RULES", f"The rule thresholds are invalid: {str(exc).splitlines()[0]}")]
    return []


def check_email(node: dict, definition: dict) -> list[Issue]:
    p = node.get("params") or {}
    issues: list[Issue] = []
    to = p.get("to")
    if isinstance(to, str) and to and not _is_ref(to):
        addrs = [a for a in re.split(r"[,;\s]+", to) if a]
        bad = [a for a in addrs if not ADDRESS.match(a)]
        if bad:
            issues.append(("error", "BAD_RECIPIENT", f"Not a valid email address: {', '.join(bad)}."))
        if len(addrs) > MAX_RECIPIENTS:
            issues.append(("error", "TOO_MANY_RECIPIENTS", f"At most {MAX_RECIPIENTS} recipients are allowed."))
    attach = p.get("attachments")
    sends_report = any(isinstance(r, str) and (r.endswith("report_file_id") or r.endswith("csv_file_id")) for r in refs_in(attach))
    if sends_report:
        anc = ancestors(node["id"], definition["edges"])
        gates = [n["id"] for n in definition["nodes"] if n["id"] in anc and n.get("type") == "approval.human"]
        if not gates:
            issues.append(("warning", "EMAIL_NO_REVIEW_GATE", "This sends a confidential report with no Human approval step before it. The send "
                           "itself will pause for approval, but add a review step so approvers see the report first."))
        elif not any(f"nodes.{g}.output.approval_id" in r for g in gates for r in refs_in(p.get("approval_id"))):
            issues.append(("warning", "EMAIL_APPROVAL_NOT_BOUND", "Set Approval to the review step's approval_id so the send is covered by that approval."))
    return issues


STATIC: dict[str, Callable[[dict, dict], list[Issue]]] = {
    "flow.condition": check_condition, "approval.human": check_approval, "data.validate": check_validate,
    "audit.analyze": check_analyze, "email.send": check_email,
}
