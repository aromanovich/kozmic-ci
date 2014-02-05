import datetime
import logging
import collections

import github3
from flask import current_app, flash, request, render_template, redirect, url_for, abort
from flask.ext.login import current_user

from kozmic import db
from kozmic.models import User, Organization, Project
from . import bp


logger = logging.getLogger(__name__)


@bp.route('/')
def index():
    user_repositories = current_user.repositories.with_entities(
        db.literal(current_user.gh_login).label('gh_owner_login'),
        User.Repository.gh_id.label('gh_id'),
        User.Repository.gh_full_name.label('gh_full_name'))

    user_org_repositories = current_user.organizations.join(
        Organization.Repository
    ).with_entities(
        Organization.gh_login.label('gh_owner_login'),
        Organization.Repository.gh_id.label('gh_id'),
        Organization.Repository.gh_full_name.label('gh_full_name'),
    )

    repositories = user_repositories.union_all(user_org_repositories).subquery()

    repositories_without_project = db.session.query(repositories).outerjoin(
        Project, repositories.c.gh_id == Project.gh_id
    ).filter(
        Project.id == None
    ).all()

    repositories_by_owner = collections.defaultdict(list)
    for gh_owner_login, gh_id, gh_full_name in repositories_without_project:
        repositories_by_owner[gh_owner_login].append((gh_id, gh_full_name))

    return render_template(
        'repos/index.html', repositories_by_owner=repositories_by_owner)


@bp.route('/sync/')
def sync():
    """Updates the organizations and repositories to which
    the user has admin access.
    """
    # Delete all the old repositories and organizations
    # (don't do batch delete to let ORM-level cascades work)
    for repo in current_user.repositories:
        db.session.delete(repo)
    for org in current_user.organizations:
        db.session.delete(org)

    # Fill the user's organizations and their repositories
    gh_orgs, gh_repos_by_org_id = current_user.get_gh_org_repos()
    for gh_org in gh_orgs:
        org = Organization(
            gh_id=gh_org.id,
            gh_login=gh_org.login,
            gh_name=gh_org.name)
        for gh_repo in gh_repos_by_org_id[gh_org.id]:
            repo = Organization.Repository.from_gh_repo(gh_repo)
            org.repositories.append(repo)
        current_user.organizations.append(org)

    # Fill the user's own repositories
    for gh_repo in current_user.get_gh_repos():
        repo = User.Repository.from_gh_repo(gh_repo)
        current_user.repositories.append(repo)

    current_user.repos_last_synchronized_at = datetime.datetime.utcnow()
    db.session.commit()

    return redirect(url_for('.index'))


@bp.route('/<int:gh_id>/on/', methods=('POST',))
def on(gh_id):
    """Creates :class:`app.models.Project` for GitHub repository
    with `gh_id`.
    """
    # First try to find the user's repository with `gh_id`
    repo = (current_user.repositories
                        .filter(User.Repository.gh_id == gh_id).first())

    # If not found, try to find such a repository among
    # the user organizations' repositories
    repo = repo or (current_user.organizations
                                .join(Organization.Repository)
                                .filter(Organization.Repository.gh_id == gh_id)
                                .with_entities(Organization.Repository).first())

    if not repo:
        abort(404)

    if Project.query.filter_by(gh_id=repo.gh_id).first():
        # If project for repository with `gh_id` already exists,
        # we should show page where the user can ask for an invite
        # to the existing project.
        # For now just show 400
        abort(400)

    project = Project(
        owner=current_user,
        gh_id=repo.gh_id,
        gh_name=repo.gh_name,
        gh_full_name=repo.gh_full_name,
        gh_login=repo.parent.gh_login,
        gh_clone_url=repo.gh_clone_url,
        gh_key_id=-1)  # -1 is just some integer to avoid integrity error
    db.session.add(project)

    ok_to_commit = project.ensure_deploy_key()
    db.session.flush()

    ok_to_commit = ok_to_commit and project.sync_memberships_with_github()

    if ok_to_commit:
        db.session.commit()
        return redirect(url_for('projects.index'))
    else:
        db.session.rollback()
        flash('Sorry, failed to create a project. Please try again later.',
              'warning')
        return redirect(url_for('.index'))
