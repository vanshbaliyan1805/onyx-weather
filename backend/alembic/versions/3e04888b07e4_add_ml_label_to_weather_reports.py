"""add ml_label to weather_reports

Revision ID: 3e04888b07e4
Revises: d588c4089cd3
Create Date: 2026-08-28 11:37:41.522800

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3e04888b07e4'
down_revision: Union[str, Sequence[str], None] = 'd588c4089cd3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "weather_reports",
        sa.Column(
            "ml_label",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Supervised training target: 0 = genuine, 1 = fabricated. Set by ingestion, never by the ML worker.",
        ),
    )
    op.create_index(
        "ix_weather_reports_ml_label",
        "weather_reports",
        ["ml_label"],
    )


def downgrade() -> None:
    op.drop_index("ix_weather_reports_ml_label", table_name="weather_reports")
    op.drop_column("weather_reports", "ml_label")
