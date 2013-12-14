"""empty message

Revision ID: 5590ef356b4f
Revises: 4da5ae2d09f5
Create Date: 2013-12-14 14:20:16.045410

"""

# revision identifiers, used by Alembic.
revision = '5590ef356b4f'
down_revision = '4da5ae2d09f5'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('build', sa.Column('gh_commit_ref', sa.String(length=200), nullable=False,
                   server_default='master'))
    op.drop_constraint('gh_commit_sha', 'build', type_='unique')
    op.create_unique_constraint('unique_ref_and_sha_within_project', 'build',
                                ['project_id', 'gh_commit_ref', 'gh_commit_sha'])
    # Drop default on `gh_commit_ref`:
    op.alter_column('build', 'gh_commit_ref', existing_type=sa.String(length=200))


def downgrade():
    op.drop_column('build', 'gh_commit_ref')
    op.drop_constraint('unique_ref_and_sha_within_project', 'build', type_='unique')
