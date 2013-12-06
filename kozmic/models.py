# coding: utf-8
"""
kozmic.models
~~~~~~~~~~~~~
"""
import datetime
import collections
import hashlib

import github3
import sqlalchemy.dialects.mysql
import flask
from flask.ext.login import UserMixin
from flask.ext.principal import Identity, RoleNeed, UserNeed
from werkzeug.utils import cached_property
from sqlalchemy.ext.declarative import declared_attr

from kozmic import db, perms


class RepositoryBase(object):
    """A base repository class to be used by :class:`HasRepositories` mixin."""
    id = db.Column(db.Integer, primary_key=True)

    #: GitHub id
    gh_id = db.Column(db.Integer, nullable=False)
    #: GitHub name (i.e., kozmic)
    gh_name = db.Column(db.String(200), nullable=False)
    #: GitHub full name (i.e., aromanovich/kozmic)
    gh_full_name = db.Column(db.String(200), nullable=False)
    #: SSH clone url
    gh_clone_url = db.Column(db.String(200), nullable=False)

    @classmethod
    def from_gh_repo(cls, gh_repo):
        """Constructs instance of `cls` from `gh_repo`.

        :type gh_repo: :class:`github3.repos.repo.Repository`
        """
        return cls(
            gh_id=gh_repo.id,
            gh_name=gh_repo.name,
            gh_full_name=gh_repo.full_name,
            gh_clone_url=gh_repo.ssh_url)  # Note: ssh_url, not clone_url


class HasRepositories(object):
    """Mixin that adds :attr:`repositories` relationship to the model.
    Repositories are stored in separate tables for each parent.
    :attr:`Repository` attribute contains model (inherited from
    :class:`RepositoryBase`) mapped to the parent's repositories table.

    This pattern is well described in
    `"Hand Coded Applications with SQLAlchemy" presentation
    <http://techspot.zzzeek.org/files/2012/hand_coded_with_sqla.key.pdf>`_
    by Mike Bayer.
    """
    @declared_attr
    def repositories(cls):
        parent_id = db.Column(
            '{}_id'.format(cls.__tablename__),
            db.Integer,
            db.ForeignKey('{}.id'.format(cls.__tablename__)),
            nullable=False)

        cls.Repository = type(
            '{}Repository'.format(cls.__name__),
            (RepositoryBase, db.Model),
            {
                '__tablename__': '{}_repository'.format(cls.__tablename__),
                'parent_id': parent_id,
            })
        return db.relationship(cls.Repository, backref='parent',
                               lazy='dynamic', cascade='all')


class User(HasRepositories, db.Model, UserMixin):
    """User account.

    .. attribute:: repositories

        Set of user repositories.

    .. attribute:: organizations

        Set of user organizations in which user has admin rights
        to at least one repository (see :class:`Organization`).
    """
    id = db.Column(db.Integer, primary_key=True)

    #: GitHub user id
    gh_id = db.Column(db.Integer, nullable=False, unique=True)
    #: GitHub user login
    gh_login = db.Column(db.String(200), nullable=False, unique=True)
    #: Human-readable GitHub name
    gh_name = db.Column(db.String(200), nullable=False)
    #: OAuth access token
    gh_access_token = db.Column(db.String(100), nullable=False)
    #: GitHub avatar URL
    gh_avatar_url = db.Column(db.String(500), nullable=False)
    #: The last time when the user's repositories and organizations
    #: were synced with GitHub
    repos_last_synchronized_at = db.Column(db.DateTime)

    def __repr__(self):
        return u'<User #{0.id} gh_id={0.gh_id} gh_login={0.gh_login}>'.format(self)

    def get_identity(self):
        """Returns user's :class:`flask.ext.principal.Identity`."""
        identity = Identity(self.id)
        for project in self.projects:
            identity.provides.add(perms.project_manager(project.id))
        for project in self.owned_projects:
            identity.provides.add(perms.project_owner(project.id))
        return identity

    def get_available_projects(self, annotate_with_latest_builds=False):
        """Returns list of :class:`Projects` that user has access to.
        If `annotate_with_latest_builds` is specified, returns list of pairs
        (:class:`Projects`, :class:`Build`) where the second element is the
        latest project build or ``None`` if the project was never built.
        """
        q = self.owned_projects.union(self.projects)
        if annotate_with_latest_builds:
            q = q.outerjoin(Build).filter(db.or_(
                Build.id == None,
                Build.created_at == db.select([db.func.max(Build.created_at)])
                     .where(Build.project_id == Project.id).correlate(Project)
            )).order_by(Build.created_at.desc()).with_entities(Project, Build)
        return q.all()

    @cached_property
    def gh(self):
        """An authenticated GitHub session for this user.

        :type: :class:`github3.github.GitHub`
        """
        return github3.login(token=self.gh_access_token)

    def get_gh_org_repos(self):
        """Retrieves data from GitHub API and returns a pair of values:

        1. :class:`set` of :class:`github3.orgs.Organization` in which
           the current user has at least one repository with admin rights;
        2. :class:`dict` mapping these organization' ids to lists of
           :class:`github3.repo.Repository` to which the current user
           has admin access.

        :type gh: :class:`github3.github.GitHub` of the current user
        """
        gh_orgs = set()
        gh_repos_by_org_id = collections.defaultdict(list)

        for gh_team in self.gh.iter_teams():
            if gh_team.permission != 'admin':
                continue

            gh_org = github3.orgs.Organization(gh_team.to_json()['organization'])
            gh_orgs.add(gh_org)

            for gh_repo in gh_team.iter_repos():
                if gh_repo not in gh_repos_by_org_id[gh_org.id]:
                    # The same repo can be in multiple teams --
                    # append only if we haven't seen `gh_repo` before
                    gh_repos_by_org_id[gh_org.id].append(gh_repo)

        return gh_orgs, gh_repos_by_org_id

    def get_gh_repos(self):
        """Retrieves data from GitHub API and returns list of
        user repositories.

        :rtype: list of :class:`github3.repo.Repository`
        """
        return list(self.gh.iter_repos(self.gh_login))


class Organization(HasRepositories, db.Model):
    """Stores a set of organization repositories that a user has
    admin access to.

    Different Kozmic users, but members of the same GitHub organization,
    will have their own :class:`Organization` entries with possibly different
    sets of repositories (because they are possibly members of different teams).

    .. attribute:: repositories
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    #: GitHub organization id
    gh_id = db.Column(db.Integer, nullable=False, index=True)
    #: GitHub organization login
    gh_login = db.Column(db.String(200), nullable=False)
    #: Human-readable GitHub name
    gh_name = db.Column(db.String(200), nullable=False)
    #: :class:`User` whose admin rights is reflected by this organization
    user = db.relationship(
        'User', backref=db.backref('organizations', lazy='dynamic'))


project_members = db.Table(
    'project_members', db.Model.metadata,
    db.Column('project_id', db.Integer, db.ForeignKey('project.id')),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('created_at', db.DateTime, nullable=False,
              default=datetime.datetime.utcnow))


class Project(db.Model):
    """Project is a GitHub repository that is being watched by
    Kozmic CI.
    """
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    #: GitHub repo id
    gh_id = db.Column(db.Integer, nullable=False, unique=True)
    #: GitHub repo name (i.e., kozmic)
    gh_name = db.Column(db.String(200), nullable=False)
    #: GitHub repo full name (i.e., aromanovich/kozmic)
    gh_full_name = db.Column(db.String(200), nullable=False)
    #: GitHub repo owner (user or organization) login
    gh_login = db.Column(db.String(200), nullable=False)
    #: SSH repo clone url
    gh_clone_url = db.Column(db.String(200), nullable=False)

    #: GitHub deploy key id
    gh_key_id = db.Column(db.Integer, nullable=False)
    #: RSA private deploy key in PEM format encrypted with the app secret key
    rsa_private_key = db.Column(db.Text, nullable=False)
    #: RSA public deploy key in OpenSSH format
    rsa_public_key = db.Column(db.Text, nullable=False)

    #: Project members
    members = db.relationship(
        'User', secondary=project_members, lazy='dynamic',
        backref=db.backref('projects', lazy='dynamic'))
    #: Project owner
    owner = db.relationship(
        'User', backref=db.backref('owned_projects', lazy='dynamic'))

    def __repr__(self):
        return u'<Project #{0.id} {0.gh_full_name}>'.format(self)

    @property
    def passphrase(self):
        secret_key_w_salt = '{}:{}'.format(
            self.gh_id, flask.current_app.config['SECRET_KEY'])
        return hashlib.sha256(secret_key_w_salt).hexdigest()

    @cached_property
    def gh(self):
        """Project's GitHub.

        :type: :class:`github3.repos.Repository`
        """
        return self.owner.gh.repository(self.gh_login, self.gh_name)

    @property
    def latest_build(self):
        """
        :type: :class:`Build`
        """
        return self.builds.order_by(Build.created_at.desc()).first()


class Hook(db.Model):
    """Reflects GitHub hook."""
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'),
                           nullable=False)

    #: GitHub hook id
    gh_id = db.Column(db.Integer, nullable=False)
    #: Title
    title = db.Column(db.String(200), nullable=False)
    #: Bash one-liner to be run at hook call
    build_script = db.Column(db.Text, nullable=False)
    #: Name of a docker image to run build script in
    #: (for example, "ubuntu" or "aromanovich/ubuntu-kozmic").
    #: Specified docker image is pulled from index.docker.io before build
    docker_image = db.Column(db.String(200), nullable=False)
    #: Project
    project = db.relationship(Project, backref=db.backref('hooks', lazy='dynamic'))


class HookCall(db.Model):
    """Reflects a fact that GitHub triggered a project hook."""
    id = db.Column(db.Integer, primary_key=True)
    hook_id = db.Column(db.Integer, db.ForeignKey('hook.id', ondelete='SET NULL'))

    #: Created at
    created_at = db.Column(db.DateTime, nullable=False,
                           default=datetime.datetime.utcnow)
    #: Pickled JSON payload from a GitHub request
    gh_payload = db.deferred(db.Column(db.PickleType, nullable=False))
    #: Hook
    hook = db.relationship(Hook, backref=db.backref('calls', lazy='dynamic'))


class Build(db.Model):
    """Reflects a project commit that triggered a project hook."""
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'),
                           nullable=False)

    #: Build number (within a project)
    number = db.Column(db.Integer, nullable=False, index=True)
    #: Commit SHA
    gh_commit_sha = db.Column(db.String(40), nullable=False, unique=True)
    #: Commit author
    gh_commit_author = db.Column(db.String(200), nullable=False)
    #: Commit message
    gh_commit_message = db.Column(db.String(2000), nullable=False)
    #: Created at
    created_at = db.Column(db.DateTime, nullable=False, index=True,
                           default=datetime.datetime.utcnow)
    #: Build status, one of the following strings:
    #: 'success', 'pending', 'failure', 'error'
    status = db.Column(db.String(40), nullable=False)
    #: Project
    project = db.relationship(Project,
                              backref=db.backref('builds', lazy='dynamic'))

    def calculate_number(self):
        """Computes and sets :attr:`number`."""
        last_number = self.project.builds.with_entities(
            db.func.max(Build.number)).scalar() or 0
        self.number = last_number + 1

    @property
    def started_at(self):
        """Time the first build step has started or None
        if there is no started steps yet.
        """
        started_ats = filter(bool, [step.started_at for step in self.steps])
        return started_ats and min(started_ats) or None

    @property
    def finished_at(self):
        """Time the last build step has finished or None
        if there is no finished steps yet.
        """
        finished_ats = filter(bool, [step.finished_at for step in self.steps])
        return finished_ats and min(finished_ats) or None

    def set_status(self, status, target_url='', description=''):
        """Sets :attr:`status` and posts it on GitHub."""
        assert status in ('success', 'pending', 'failure', 'error')
        rv = self.project.gh.create_status(
            self.gh_commit_sha, status,
            target_url=target_url or self.url, description=description)
        self.status = status

    @property
    def url(self):
        return flask.url_for(
            'projects.build', project_id=self.project.id, id_or_latest=self.id)


class BuildStep(db.Model):
    """Corresponds to a hook call and contains results of a running
    hook build script.
    """
    id = db.Column(db.Integer, primary_key=True)
    build_id = db.Column(db.Integer, db.ForeignKey('build.id'),
                         nullable=False)
    hook_call_id = db.Column(db.Integer, db.ForeignKey('hook_call.id'),
                             nullable=False)

    # Time build step has started or None
    started_at = db.Column(db.DateTime)
    # Time build step has finished or None
    finished_at = db.Column(db.DateTime)
    # Build return code
    return_code = db.Column(db.Integer)
    # Build log
    stdout = db.deferred(db.Column(sqlalchemy.dialects.mysql.MEDIUMBLOB))
    # uuid of a Celery task that is running a build step
    task_uuid = db.Column(db.String(36))
    #: :class:`Build`
    build = db.relationship(Build, backref=db.backref('steps', lazy='dynamic'))
    #: :class:`HookCall`
    hook_call = db.relationship('HookCall')

    def started(self):
        """Sets :attr:`started_at` and updates :attr:`build` status.
        **Must** be called at build step start time.
        """
        self.started_at = datetime.datetime.utcnow()
        description = 'Kozmic build #{0} is pending.'.format(self.build.id)
        self.build.set_status('pending', description=description)

    def finished(self, return_code):
        """Sets :attr:`finished_at` and updates :attr:`build` status.
        **Must** be called at build step finish time.
        """
        self.return_code = return_code
        self.finished_at = datetime.datetime.utcnow()

        if return_code != 0:
            description = (
                'Kozmic build #{0} has failed '
                'because of the "{1}" hook.'.format(
                    self.build.id,
                    self.hook_call.hook.title))
            self.build.set_status('failure', description=description)
            return

        steps = self.build.steps
        all_other_steps_finished = all(step.finished_at for step in steps
                                       if step.id != self.id)
        all_other_steps_succeeded = all(step.return_code == 0 for step in steps
                                        if step.id != self.id)
        if all_other_steps_finished and all_other_steps_succeeded:
            description = 'Kozmic build #{0} has passed.'.format(self.build.id)
            self.build.set_status('success', description=description)
            return
