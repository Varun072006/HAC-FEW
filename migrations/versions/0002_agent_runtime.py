"""Agent runtime: agent registry, plans, tool executions, resumable task state, budgets.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _uniques(table: str) -> set[str]:
    return {u["name"] for u in sa.inspect(op.get_bind()).get_unique_constraints(table) if u.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    run_cols = _cols("runs")
    for col in [sa.Column("objective", sa.Text), sa.Column("plan_id", sa.String(40)),
                sa.Column("budget", sa.JSON), sa.Column("agent_snapshot", sa.JSON),
                sa.Column("cancel_requested", sa.Boolean, nullable=False, server_default=sa.false())]:
        if col.name not in run_cols:
            op.add_column("runs", col)

    node_cols = _cols("node_runs")
    for col in [sa.Column("agent_version", sa.Integer), sa.Column("delegation", sa.JSON),
                sa.Column("usage", sa.JSON), sa.Column("checkpoint", sa.JSON),
                sa.Column("failure_class", sa.String(30))]:
        if col.name not in node_cols:
            op.add_column("node_runs", col)
    if not sqlite:  # SQLite does not enforce VARCHAR length
        op.alter_column("node_runs", "agent", existing_type=sa.String(30), type_=sa.String(60))

    appr_cols = _cols("approvals")
    with op.batch_alter_table("approvals") as b:
        if not sqlite:
            b.alter_column("agent", existing_type=sa.String(30), type_=sa.String(60))
        if "op_index" not in appr_cols:
            b.add_column(sa.Column("op_index", sa.Integer, nullable=False, server_default="0"))
        if "evidence" not in appr_cols:
            b.add_column(sa.Column("evidence", sa.JSON))
        if "uq_approval_node" in _uniques("approvals"):
            b.drop_constraint("uq_approval_node", type_="unique")
        b.create_unique_constraint("uq_approval_node_op", ["run_id", "node_id", "op_index"])

    if not _has_table("agents"):
        op.create_table(
            "agents",
            sa.Column("id", sa.String(60), primary_key=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("current_version", sa.Integer, nullable=False),
            sa.Column("created_by", sa.String(40), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False))
    if not _has_table("agent_versions"):
        op.create_table(
            "agent_versions",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("agent_id", sa.String(60), sa.ForeignKey("agents.id"), nullable=False),
            sa.Column("version", sa.Integer, nullable=False),
            sa.Column("level", sa.Integer, nullable=False),
            sa.Column("parent_id", sa.String(60)),
            sa.Column("config", sa.JSON, nullable=False),
            sa.Column("change_note", sa.Text),
            sa.Column("created_by", sa.String(40), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint("agent_id", "version", name="uq_agent_version"))
        op.create_index("ix_agent_versions_parent", "agent_versions", ["parent_id"])
    if not _has_table("plans"):
        op.create_table(
            "plans",
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("objective", sa.Text, nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("planner", sa.String(30), nullable=False),
            sa.Column("plan", sa.JSON, nullable=False),
            sa.Column("issues", sa.JSON, nullable=False),
            sa.Column("usage", sa.JSON),
            sa.Column("created_by", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("run_id", sa.String(40)))
    if not _has_table("tool_executions"):
        op.create_table(
            "tool_executions",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("idempotency_key", sa.String(64), nullable=False),
            sa.Column("run_id", sa.String(40), sa.ForeignKey("runs.id"), nullable=False),
            sa.Column("node_id", sa.String(60), nullable=False),
            sa.Column("op_index", sa.Integer, nullable=False),
            sa.Column("tool", sa.String(80), nullable=False),
            sa.Column("effect", sa.String(12), nullable=False),
            sa.Column("status", sa.String(12), nullable=False),
            sa.Column("args", sa.JSON), sa.Column("result", sa.JSON), sa.Column("error", sa.Text),
            sa.Column("started_at", sa.DateTime, nullable=False),
            sa.Column("finished_at", sa.DateTime),
            sa.Column("latency_ms", sa.Integer),
            sa.UniqueConstraint("idempotency_key", name="uq_tool_idem"))
        op.create_index("ix_tool_exec_run", "tool_executions", ["run_id"])


def downgrade() -> None:
    op.drop_table("tool_executions")
    op.drop_table("plans")
    op.drop_table("agent_versions")
    op.drop_table("agents")
    with op.batch_alter_table("approvals") as b:
        b.drop_constraint("uq_approval_node_op", type_="unique")
        b.drop_column("evidence")
        b.drop_column("op_index")
        b.create_unique_constraint("uq_approval_node", ["run_id", "node_id"])
    with op.batch_alter_table("node_runs") as b:
        for c in ("failure_class", "checkpoint", "usage", "delegation", "agent_version"):
            b.drop_column(c)
    with op.batch_alter_table("runs") as b:
        for c in ("cancel_requested", "agent_snapshot", "budget", "plan_id", "objective"):
            b.drop_column(c)
