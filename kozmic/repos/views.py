import datetime

import github3
from Crypto.PublicKey import RSA
from flask import current_app, request, render_template, redirect, url_for, abort
from flask.ext.login import current_user, login_required

from kozmic import db
from kozmic.models import User, Organization, Project
from . import bp


# TODO Make a pull request!
# Monkeypatch GitHub library
def iter_teams(self, type=None, sort=None, direction=None,
               number=-1, etag=None):
    url = self._build_url('user', 'teams')

    params = {}
    if type in ('all', 'owner', 'member'):
        params.update(type=type)
    if sort in ('created', 'updated', 'pushed', 'full_name'):
        params.update(sort=sort)
    if direction in ('asc', 'desc'):
        params.update(direction=direction)

    return self._iter(int(number), url, github3.orgs.Team, params, etag)
github3.github.GitHub.iter_teams = iter_teams
# / TODO


@bp.route('/')
@login_required
def index():
    existing_projects = dict(current_user.projects.with_entities(
        Project.gh_id, Project.id).all())
    return render_template(
        'repos/index.html', existing_projects=existing_projects)


@bp.route('/sync/')
@login_required
def sync():
    """Updates the organizations and repositories to which
    the user has admin access.
    """
    # Delete all the old repositories and organizations
    # (don't do batch delete to get ORM-level cascades working)
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


@bp.route('/<int:gh_id>/on/', methods=['POST'])
@login_required
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
        # If repository is not found, show 404
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
        gh_key_id=-1)  # Just some integer to avoid integrity error

    rsa_key = RSA.generate(2048)
    project.rsa_private_key = rsa_key.exportKey(
        format='PEM', passphrase=project.passphrase)
    project.rsa_public_key = rsa_key.publickey().exportKey(format='OpenSSH')
    
    db.session.add(project)
    db.session.flush()
        
    try:
        gh_key = project.gh.create_key('Kozmic CI', project.rsa_public_key)
        project.gh_key_id = gh_key.id
    except github3.GitHubError as exc:
        logger.warning(
            'GitHub API call to add {project!r}\'s deploy key has failed. '
            'The current user is {user!r}. The exception was '
            '"{exc!r} and with errors {errors!r}.".'.format(
                project=project,
                user=current_user,
                exc=exc,
                errors=exc.errors))
        db.session.rollback()
        flash('Sorry, failed to create a project. Please try again later.',
              'warning')
    else:
        db.session.commit()

    return redirect(url_for('index'))
