"""empty message

Revision ID: 1b5bbc75de44
Revises: 1531599e3534
Create Date: 2014-01-02 20:52:28.389571

"""

# revision identifiers, used by Alembic.
revision = '1b5bbc75de44'
down_revision = '1531599e3534'

from alembic import op
import sqlalchemy as sa

from kozmic.models import db


def upgrade():
    op.create_index('ix_build_created_at', 'build', ['created_at'], unique=False)
    op.create_index('ix_build_number', 'build', ['number'], unique=False)
    op.add_column('hook_call', sa.Column('build_id', sa.Integer(), nullable=False))
    try:
        from kozmic.models import Job
        for job in Job.query.all():
            job.hook_call.build_id = job.build_id
    finally:
        db.session.commit()
    op.create_unique_constraint('unique_hook_call_within_build', 'hook_call', ['build_id', 'hook_id'])
    op.create_index('ix_organization_gh_id', 'organization', ['gh_id'], unique=False)


def downgrade():
    op.drop_index('ix_organization_gh_id', 'organization')
    op.drop_constraint('unique_hook_call_within_build', 'hook_call')
    op.drop_column('hook_call', 'build_id')
    op.drop_index('ix_build_number', 'build')
    op.drop_index('ix_build_created_at', 'build')
