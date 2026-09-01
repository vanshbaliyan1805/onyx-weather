"""add hybrid scoring columns

-----------------------------------------------------------------------------
Do not copy this into alembic/versions/ directly - `down_revision` has to
point at your current head. Generate the skeleton first:

    cd backend
    alembic revision -m "add hybrid scoring columns"

Then paste the two functions below into the file it prints, and:

    alembic upgrade head

Only needed for Supabase. The local SQLite path gets these columns from
hybrid_worker.py on its first run.

Also add them to backend/app/models/weather_report.py so the model stays the
source of truth:

    # Hybrid scoring (written by hybrid/hybrid_worker.py)
    hybrid_score = Column(Float, index=True, nullable=True,
        comment="0-1 blend of model, measurement, physics and source")
    hybrid_signals = Column(Text, nullable=True,
        comment="JSON: each signal, its weight, its contribution, the driver")

`verdict` already exists from the measurement migration; if you skipped that
one, add it here too.
-----------------------------------------------------------------------------
"""

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "weather_reports",
        sa.Column("hybrid_score", sa.Float(), nullable=True,
                  comment="0-1 blend of model, measurement, physics, source"),
    )
    op.add_column(
        "weather_reports",
        sa.Column("hybrid_signals", sa.Text(), nullable=True,
                  comment="JSON breakdown of the contributing signals"),
    )
    # The dashboard's main queries are "worst first" and "everything above
    # the fake threshold", and both are range scans on this column.
    op.create_index(
        "ix_weather_reports_hybrid_score", "weather_reports", ["hybrid_score"],
    )


def downgrade() -> None:
    op.drop_index("ix_weather_reports_hybrid_score",
                  table_name="weather_reports")
    op.drop_column("weather_reports", "hybrid_signals")
    op.drop_column("weather_reports", "hybrid_score")
