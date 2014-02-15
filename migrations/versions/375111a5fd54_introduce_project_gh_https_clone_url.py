"""Introduce Project.gh_https_clone_url

Revision ID: 375111a5fd54
Revises: 25ecf1c9b3fb
Create Date: 2014-02-08 15:17:47.239898

"""

revision = '375111a5fd54'
down_revision = '25ecf1c9b3fb'


from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from kozmic.models import db, Project


def upgrade():
    op.add_column('organization_repository', sa.Column('gh_https_clone_url', sa.String(length=200), nullable=False))
    op.add_column('organization_repository', sa.Column('gh_ssh_clone_url', sa.String(length=200), nullable=False))
    op.add_column('project', sa.Column('gh_https_clone_url', sa.String(length=200), nullable=False))
    op.add_column('project', sa.Column('gh_ssh_clone_url', sa.String(length=200), nullable=False))
    op.add_column('user_repository', sa.Column('gh_https_clone_url', sa.String(length=200), nullable=False))
    op.add_column('user_repository', sa.Column('gh_ssh_clone_url', sa.String(length=200), nullable=False))
    for project in Project.query.all():
        project.gh_ssh_clone_url = project.gh.ssh_url
        project.gh_https_clone_url = project.gh.clone_url
        db.session.add(project)
    db.session.commit()
    op.drop_column('organization_repository', 'gh_clone_url')
    op.drop_column('project', 'gh_clone_url')
    op.drop_column('user_repository', 'gh_clone_url')


def downgrade():
    op.add_column('user_repository', sa.Column('gh_clone_url', mysql.VARCHAR(length=200), nullable=False))
    op.drop_column('user_repository', 'gh_ssh_clone_url')
    op.drop_column('user_repository', 'gh_https_clone_url')
    op.add_column('project', sa.Column('gh_clone_url', mysql.VARCHAR(length=200), nullable=False))
    op.drop_column('project', 'gh_ssh_clone_url')
    op.drop_column('project', 'gh_https_clone_url')
    op.add_column('organization_repository', sa.Column('gh_clone_url', mysql.VARCHAR(length=200), nullable=False))
    op.drop_column('organization_repository', 'gh_ssh_clone_url')
    op.drop_column('organization_repository', 'gh_https_clone_url')
