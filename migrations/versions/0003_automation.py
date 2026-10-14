"""Business automation: stored files, email deliveries, run result record, per-node attempt epoch.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if "result" not in _cols("runs"):
        op.add_column("runs", sa.Column("result", sa.JSON))
    if "epoch" not in _cols("node_runs"):
        op.add_column("node_runs", sa.Column("epoch", sa.Integer, nullable=False, server_default="0"))
    if not _has_table("files"):
        op.create_table(
            "files",
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("content_type", sa.String(120), nullable=False),
            sa.Column("size", sa.Integer, nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("storage_key", sa.String(200), nullable=False),
            sa.Column("sensitivity", sa.String(20), nullable=False),
            sa.Column("uploaded_by", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("run_id", sa.String(40)),
            sa.Column("node_id", sa.String(60)),
            sa.Column("meta", sa.JSON),
            sa.Column("created_at", sa.DateTime, nullable=False))
        op.create_index("ix_files_run", "files", ["run_id"])
    if not _has_table("email_deliveries"):
        op.create_table(
            "email_deliveries",
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("run_id", sa.String(40), nullable=False),
            sa.Column("node_id", sa.String(60), nullable=False),
            sa.Column("connector", sa.String(40), nullable=False),
            sa.Column("mode", sa.String(10), nullable=False),
            sa.Column("sender", sa.String(200), nullable=False),
            sa.Column("recipients", sa.JSON, nullable=False),
            sa.Column("subject", sa.String(300), nullable=False),
            sa.Column("body_sha256", sa.String(64), nullable=False),
            sa.Column("attachments", sa.JSON, nullable=False),
            sa.Column("status", sa.String(12), nullable=False),
            sa.Column("attempts", sa.Integer, nullable=False),
            sa.Column("provider_message_id", sa.String(200)),
            sa.Column("error", sa.Text),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("sent_at", sa.DateTime))
        op.create_index("ix_email_run", "email_deliveries", ["run_id"])


def downgrade() -> None:
    op.drop_table("email_deliveries")
    op.drop_table("files")
    with op.batch_alter_table("node_runs") as b:
        b.drop_column("epoch")
    with op.batch_alter_table("runs") as b:
        b.drop_column("result")
