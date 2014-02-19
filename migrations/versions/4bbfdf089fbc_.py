"""empty message

Revision ID: 4bbfdf089fbc
Revises: 2cc431e5815b
Create Date: 2014-01-07 23:46:14.694649

"""

# revision identifiers, used by Alembic.
revision = '4bbfdf089fbc'
down_revision = '2cc431e5815b'

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


def upgrade():
    op.add_column('membership', sa.Column('allows_management', sa.Boolean(), nullable=False))
    op.alter_column('membership', 'project_id',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=False)
    op.alter_column('membership', 'user_id',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=False)


def downgrade():
    op.alter_column('membership', 'user_id',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=True)
    op.alter_column('membership', 'project_id',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=True)
    op.drop_column('membership', 'allows_management')
