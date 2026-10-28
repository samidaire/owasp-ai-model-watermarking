"""jobs.model: the catalogue id a model_test job tests (v1 JobInfo.model, "Model under test").

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as b:
        b.add_column(sa.Column("model", sa.String(length=300), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as b:
        b.drop_column("model")
