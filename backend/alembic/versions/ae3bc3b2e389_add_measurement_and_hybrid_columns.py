"""add measurement and hybrid columns

Revision ID: ae3bc3b2e389
Revises: 3e04888b07e4
Create Date: 2026-09-01 15:36:59.423900

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ae3bc3b2e389'
down_revision: Union[str, Sequence[str], None] = '3e04888b07e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    from sqlalchemy import inspect
    inspector = inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('weather_reports')]

    # Measurement Columns
    if 'measurement_check' not in columns:
        op.add_column('weather_reports', sa.Column('measurement_check', sa.String(), nullable=True, comment="agrees | contradicted | unverifiable"))
    if 'measurement_note' not in columns:
        op.add_column('weather_reports', sa.Column('measurement_note', sa.Text(), nullable=True))
    if 'measurement_severity' not in columns:
        op.add_column('weather_reports', sa.Column('measurement_severity', sa.Float(), nullable=True, comment="0-1 how badly it missed"))
    if 'measurement_checked_at' not in columns:
        op.add_column('weather_reports', sa.Column('measurement_checked_at', sa.DateTime(timezone=True), nullable=True))

    # Hybrid Columns
    if 'hybrid_score' not in columns:
        op.add_column('weather_reports', sa.Column('hybrid_score', sa.Float(), nullable=True, comment="0-1 blend of model, measurement, physics and source"))
        op.create_index('ix_weather_reports_hybrid_score', 'weather_reports', ['hybrid_score'])
    if 'hybrid_signals' not in columns:
        op.add_column('weather_reports', sa.Column('hybrid_signals', sa.Text(), nullable=True, comment="JSON breakdown of contributing signals"))
    if 'verdict' not in columns:
        op.add_column('weather_reports', sa.Column('verdict', sa.String(), nullable=True, comment="fake | suspect | ok | unchecked"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('weather_reports', 'verdict')
    op.drop_column('weather_reports', 'hybrid_signals')
    op.drop_index('ix_weather_reports_hybrid_score', table_name='weather_reports')
    op.drop_column('weather_reports', 'hybrid_score')
    op.drop_column('weather_reports', 'measurement_checked_at')
    op.drop_column('weather_reports', 'measurement_severity')
    op.drop_column('weather_reports', 'measurement_note')
    op.drop_column('weather_reports', 'measurement_check')
