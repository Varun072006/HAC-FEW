"""Baseline: the platform schema as it existed before the agent runtime.

Databases created earlier with `create_all` already have these tables; each is created only if absent,
so stamping and upgrading an existing database is safe.

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _missing(name: str) -> bool:
    return name not in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _missing("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("username", sa.String(60), nullable=False, unique=True),
            sa.Column("display_name", sa.String(120), nullable=False),
            sa.Column("role", sa.String(40), nullable=False),
            sa.Column("employee_id", sa.String(50)),
            sa.Column("password_hash", sa.String(300), nullable=False),
            sa.Column("active", sa.Boolean, nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False))
    if _missing("workflows"):
        op.create_table(
            "workflows",
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("description", sa.Text, nullable=False),
            sa.Column("definition", sa.JSON, nullable=False),
            sa.Column("version", sa.Integer, nullable=False),
            sa.Column("template_id", sa.String(60)),
            sa.Column("created_by", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False))
    if _missing("runs"):
        op.create_table(
            "runs",
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("workflow_id", sa.String(40), sa.ForeignKey("workflows.id"), nullable=False),
            sa.Column("workflow_name", sa.String(160), nullable=False),
            sa.Column("workflow_version", sa.Integer, nullable=False),
            sa.Column("definition_snapshot", sa.JSON, nullable=False),
            sa.Column("inputs", sa.JSON, nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("started_by", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("started_by_role", sa.String(40), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("finished_at", sa.DateTime),
            sa.Column("error", sa.Text),
            sa.Column("next_seq", sa.Integer, nullable=False))
        op.create_index("ix_runs_status", "runs", ["status"])
        op.create_index("ix_runs_started_by", "runs", ["started_by"])
    if _missing("node_runs"):
        op.create_table(
            "node_runs",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.String(40), sa.ForeignKey("runs.id"), nullable=False),
            sa.Column("node_id", sa.String(60), nullable=False),
            sa.Column("node_type", sa.String(60), nullable=False),
            sa.Column("label", sa.String(160)),
            sa.Column("agent", sa.String(30)),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("attempts", sa.Integer, nullable=False),
            sa.Column("input", sa.JSON), sa.Column("output", sa.JSON), sa.Column("error", sa.Text),
            sa.Column("policy", sa.JSON), sa.Column("tool_calls", sa.JSON), sa.Column("summary", sa.Text),
            sa.Column("started_at", sa.DateTime), sa.Column("finished_at", sa.DateTime),
            sa.Column("latency_ms", sa.Integer),
            sa.UniqueConstraint("run_id", "node_id", name="uq_node_run"))
    if _missing("run_events"):
        op.create_table(
            "run_events",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.String(40), sa.ForeignKey("runs.id"), nullable=False),
            sa.Column("seq", sa.Integer, nullable=False),
            sa.Column("ts", sa.DateTime, nullable=False),
            sa.Column("type", sa.String(40), nullable=False),
            sa.Column("node_id", sa.String(60)),
            sa.Column("data", sa.JSON, nullable=False),
            sa.UniqueConstraint("run_id", "seq", name="uq_run_event_seq"))
    if _missing("approvals"):
        op.create_table(
            "approvals",
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("run_id", sa.String(40), sa.ForeignKey("runs.id"), nullable=False),
            sa.Column("node_id", sa.String(60), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("risk_level", sa.String(10), nullable=False),
            sa.Column("rule_id", sa.String(60)),
            sa.Column("reason", sa.Text, nullable=False),
            sa.Column("tool_name", sa.String(80), nullable=False),
            sa.Column("agent", sa.String(30), nullable=False),
            sa.Column("params_snapshot", sa.JSON, nullable=False),
            sa.Column("required_slots", sa.JSON, nullable=False),
            sa.Column("requested_by", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("requested_at", sa.DateTime, nullable=False),
            sa.Column("decided_at", sa.DateTime),
            sa.UniqueConstraint("run_id", "node_id", name="uq_approval_node"))
        op.create_index("ix_approvals_status", "approvals", ["status"])
    if _missing("approval_decisions"):
        op.create_table(
            "approval_decisions",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("approval_id", sa.String(40), sa.ForeignKey("approvals.id"), nullable=False),
            sa.Column("approver_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("approver_role", sa.String(40), nullable=False),
            sa.Column("decision", sa.String(10), nullable=False),
            sa.Column("comment", sa.Text),
            sa.Column("slot_index", sa.Integer),
            sa.Column("decided_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint("approval_id", "approver_id", name="uq_decision_approver"),
            sa.UniqueConstraint("approval_id", "slot_index", name="uq_decision_slot"))
    if _missing("audit_events"):
        op.create_table(
            "audit_events",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("ts", sa.DateTime, nullable=False),
            sa.Column("actor_type", sa.String(20), nullable=False),
            sa.Column("actor_id", sa.String(60), nullable=False),
            sa.Column("actor_role", sa.String(40)),
            sa.Column("action", sa.String(80), nullable=False),
            sa.Column("resource_type", sa.String(40)),
            sa.Column("resource_id", sa.String(60)),
            sa.Column("run_id", sa.String(40)),
            sa.Column("outcome", sa.String(20), nullable=False),
            sa.Column("risk", sa.String(10)),
            sa.Column("detail", sa.JSON, nullable=False),
            sa.Column("prev_hash", sa.String(64), nullable=False),
            sa.Column("hash", sa.String(64), nullable=False))
        op.create_index("ix_audit_run", "audit_events", ["run_id"])
        op.create_index("ix_audit_action", "audit_events", ["action"])


def downgrade() -> None:
    for t in ("audit_events", "approval_decisions", "approvals", "run_events", "node_runs", "runs", "workflows", "users"):
        op.drop_table(t)
