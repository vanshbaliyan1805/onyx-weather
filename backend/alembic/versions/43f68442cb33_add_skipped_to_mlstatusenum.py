"""Add skipped to mlstatusenum

Revision ID: 43f68442cb33
Revises: 6d8bf6b36ed1
Create Date: 2026-09-02 13:51:05.359138

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '43f68442cb33'
down_revision: Union[str, Sequence[str], None] = '6d8bf6b36ed1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE mlstatusenum ADD VALUE IF NOT EXISTS 'skipped'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres doesn't support dropping enum values cleanly.
    pass
