"""Introduce Project.is_public field

Revision ID: 1c314d48261a
Revises: 390c1805c002
Create Date: 2014-02-07 21:01:43.164197

"""

# revision identifiers, used by Alembic.
revision = '1c314d48261a'
down_revision = '390c1805c002'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('organization_repository', sa.Column('is_public', sa.Boolean(), nullable=False))
    op.add_column('project', sa.Column('is_public', sa.Boolean(), nullable=False))
    op.add_column('user_repository', sa.Column('is_public', sa.Boolean(), nullable=False))


def downgrade():
    op.drop_column('user_repository', 'is_public')
    op.drop_column('project', 'is_public')
    op.drop_column('organization_repository', 'is_public')
