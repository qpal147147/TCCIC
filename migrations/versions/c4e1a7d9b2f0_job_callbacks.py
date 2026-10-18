"""job_callbacks: one row per callback subscription

Replaces crawl_jobs.callback_url / callback_status, which could hold only one
URL per job — a duplicate submission answered with an existing job needs to
subscribe to it too. Both columns were reserved in the baseline and never
written, so nothing is migrated across.

Revision ID: c4e1a7d9b2f0
Revises: bb668488f8ae
Create Date: 2026-10-17 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e1a7d9b2f0'
down_revision: Union[str, Sequence[str], None] = 'bb668488f8ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('job_callbacks',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('job_id', sa.String(length=36), nullable=False),
    sa.Column('callback_url', sa.String(length=1024), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('job_callbacks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_job_callbacks_job_id'), ['job_id'], unique=False)

    with op.batch_alter_table('crawl_jobs', schema=None) as batch_op:
        batch_op.drop_column('callback_status')
        batch_op.drop_column('callback_url')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('crawl_jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('callback_url', sa.String(length=1024), nullable=True))
        batch_op.add_column(sa.Column('callback_status', sa.String(length=16), nullable=True))

    with op.batch_alter_table('job_callbacks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_job_callbacks_job_id'))

    op.drop_table('job_callbacks')
