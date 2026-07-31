"""add completed_by_user_id to trash and cleaning logs

Revision ID: 70b92b1706d2
Revises: 196b4d67311f
Create Date: 2026-07-31 16:05:45.496469

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '70b92b1706d2'
down_revision: Union[str, None] = '196b4d67311f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite can't ALTER a table to add a constraint directly — batch mode
    # emulates it via copy-and-move (new table, copy rows, swap in).
    with op.batch_alter_table("cleaning_log") as batch_op:
        batch_op.add_column(sa.Column("completed_by_user_id", sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            "fk_cleaning_log_completed_by_user_id_users", "users", ["completed_by_user_id"], ["telegram_id"]
        )
    with op.batch_alter_table("trash_log") as batch_op:
        batch_op.add_column(sa.Column("completed_by_user_id", sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            "fk_trash_log_completed_by_user_id_users", "users", ["completed_by_user_id"], ["telegram_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("trash_log") as batch_op:
        batch_op.drop_constraint("fk_trash_log_completed_by_user_id_users", type_="foreignkey")
        batch_op.drop_column("completed_by_user_id")
    with op.batch_alter_table("cleaning_log") as batch_op:
        batch_op.drop_constraint("fk_cleaning_log_completed_by_user_id_users", type_="foreignkey")
        batch_op.drop_column("completed_by_user_id")
