"""Introduce DeployKey entity

Revision ID: 25ecf1c9b3fb
Revises: 1c314d48261a
Create Date: 2014-02-08 02:56:34.174597

"""

# revision identifiers, used by Alembic.
revision = '25ecf1c9b3fb'
down_revision = '1c314d48261a'


import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

from kozmic.models import db, DeployKey, Project


def upgrade():
    op.create_table('deploy_key',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('gh_id', sa.Integer(), nullable=False),
    sa.Column('rsa_private_key', sa.Text(), nullable=False),
    sa.Column('rsa_public_key', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['project.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    select = db.select(['id', 'is_public', 'rsa_public_key', 'rsa_private_key', 'gh_key_id'],
                       from_obj=Project.__tablename__)
    for id, is_public, rsa_public_key, rsa_private_key, gh_key_id \
            in db.session.execute(select).fetchall():
        if is_public:
            continue
        insert = DeployKey.__table__.insert().values(
            project_id=id,
            rsa_public_key=rsa_public_key,
            rsa_private_key=rsa_private_key,
            gh_id=gh_key_id)
        db.session.execute(insert)
    db.session.commit()
    op.drop_column(u'project', 'rsa_public_key')
    op.drop_column(u'project', 'rsa_private_key')
    op.drop_column(u'project', 'gh_key_id')


def downgrade():
    op.add_column(u'project', sa.Column('gh_key_id', mysql.INTEGER(display_width=11), nullable=False))
    op.add_column(u'project', sa.Column('rsa_private_key', mysql.MEDIUMTEXT(), nullable=False))
    op.add_column(u'project', sa.Column('rsa_public_key', mysql.MEDIUMTEXT(), nullable=False))
    op.drop_table('deploy_key')
