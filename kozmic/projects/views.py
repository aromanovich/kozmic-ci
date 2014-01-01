import logging

import github3
from flask import (Response, current_app, render_template, redirect,
                   flash, request, url_for)
from flask.ext.login import current_user

from . import bp
from .forms import HookForm, MemberForm
from kozmic import db, perms
from kozmic.models import Project, Hook, Build, Job, User


logger = logging.getLogger(__name__)


@bp.route('/')
def index():
    available_projects = current_user.get_available_projects()
    if not available_projects:
        return redirect(url_for('repos.index'))
    else:
        return redirect(url_for('.show', id=available_projects[0].id))


@bp.route('/<int:id>/')
def show(id):
    project = Project.query.get_or_404(id)
    return redirect(url_for('.build', project_id=id, id='latest'))


@bp.route('/<int:id>/history/')
def history(id):
    project = Project.query.get_or_404(id)
    builds = project.builds.order_by(Build.id.desc()).all()
    if not builds:
        return redirect(url_for('.settings', id=id))
    return render_template(
        'projects/history.html',
        project=project,
        builds=builds)


@bp.route('/<int:project_id>/builds/<id>/')
def build(project_id, id):
    project = Project.query.get_or_404(project_id)

    if id == 'latest':
        build = project.get_latest_build(ref=request.args.get('ref'))
        if not build:
            return redirect(url_for('.settings', id=project_id))
    else:
        try:
            build_id = int(id)
        except ValueError:
            abort(404)
        build = project.builds.filter_by(id=build_id).first_or_404()

    job = build.jobs.first()  # TODO Show first not finished job

    return render_template(
        'projects/job.html',
        is_build_latest=(id == 'latest'),
        project=project,
        build=build,
        job=job)


@bp.route('/<int:project_id>/builds/<int:build_id>/jobs/<int:id>/')
def job(project_id, build_id, id):
    project = Project.query.get_or_404(project_id)
    build = project.builds.filter_by(id=build_id).first_or_404()
    job = build.jobs.filter_by(id=id).first_or_404()

    print type(job.stdout), '!'

    return render_template(
        'projects/job.html',
        project=project,
        tailer_url_template=current_app.config['TAILER_URL_TEMPLATE'],
        build=build,
        job=job)


@bp.route('/<int:project_id>/jobs/<int:id>/log/')
def job_log(project_id, id):
    project = Project.query.get_or_404(project_id)
    job = project.builds.join(Job).filter(
        Job.id == id).with_entities(Job).first_or_404()
    return Response(job.stdout, mimetype='text/plain')


@bp.route('/<int:project_id>/job/<int:id>/restart/')
def job_restart(project_id, id):
    # Import at runtime for easier mocking:
    from kozmic.builds.tasks import restart_job

    project = Project.query.get_or_404(project_id)
    job = project.builds.join(Job).filter(
        Job.id == id).with_entities(Job).first_or_404()
    restart_job.delay(job.id)
    job.build.set_status('enqueued')
    db.session.commit()
    return redirect(url_for('.build', project_id=project.id, id=job.build.id))


@bp.route('/<int:id>/settings/')
def settings(id):
    project = Project.query.get_or_404(id)
    return render_template(
        'projects/settings.html', project=project,
        fqdn=current_app.config['SERVER_NAME'])


@bp.route('/<int:project_id>/hooks/add/', methods=['GET', 'POST'])
def add_hook(project_id):
    project = Project.query.get_or_404(project_id)

    form = HookForm(request.form)
    if form.validate_on_submit():
        hook = Hook(project=project)
        form.populate_obj(hook)
        db.session.add(hook)

        hook.gh_id = -1  # Just some integer to avoid integrity error
        db.session.flush()  # Flush SQL to get `hook.id`

        try:
            gh_hook = project.gh.create_hook(
                name='web',
                config={
                    'url': url_for('builds.hook', id=hook.id, _external=True),
                    'content_type': 'json',
                },
                events=['push', 'pull_request'],
                active=True)
        except github3.GitHubError as exc:
            logger.warning(
                'GitHub API call to create {project!r}\'s hook has failed. '
                'The current user is {user!r}. The exception was '
                '"{exc!r} and with errors {errors!r}.".'.format(
                    project=project,
                    user=current_user,
                    exc=exc,
                    errors=exc.errors))
            db.session.rollback()
            flash('Sorry, failed to create a hook. Please try again later.',
                  'warning')
        else:
            hook.gh_id = gh_hook.id
            db.session.commit()
        return redirect(url_for('.settings', id=project_id))
    else:
        return render_template(
            'projects/add-hook.html', project=project, form=form)


@bp.route('/<int:project_id>/hooks/<int:hook_id>/edit/', methods=['GET', 'POST'])
def edit_hook(project_id, hook_id):
    project = Project.query.get_or_404(project_id)
    hook = project.hooks.filter_by(id=hook_id).first_or_404()

    form = HookForm(request.form, obj=hook)
    if form.validate_on_submit():
        form.populate_obj(hook)
        db.session.add(hook)
        db.session.commit()
        return redirect(url_for('.settings', id=project_id))
    else:
        return render_template(
            'projects/edit-hook.html', project=project, form=form)


@bp.route('/<int:project_id>/hooks/<int:hook_id>/delete/', methods=['POST'])
def delete_hook(project_id, hook_id):
    project = Project.query.get_or_404(project_id)
    hook = project.hooks.filter_by(id=hook_id).first_or_404()

    db.session.delete(hook)

    gh_hook = project.gh.hook(hook.gh_id)
    if gh_hook:
        try:
            gh_hook.delete()
        except github3.GitHubError as exc:
            logger.warning(
                'GitHub API call to delete {hook!r} has failed. '
                'The current user is {user!r}. The exception was '
                '"{exc!r} and it\'s errors was {errors!r}.".'.format(
                    hook=hook,
                    user=current_user,
                    exc=exc,
                    errors=exc.errors))
            db.session.rollback()
    else:
        logger.warning(
            'GitHub hook for {hook!r} was not found.'.format(hook=hook))
    db.session.commit()
    return redirect(url_for('.settings', id=project_id))


@bp.route('/<int:project_id>/members/add/', methods=['GET', 'POST'])
def add_member(project_id):
    project = Project.query.get_or_404(project_id)

    form = MemberForm(request.form)
    if form.validate_on_submit():
        gh_login = form.gh_login.data
        user = User.query.filter_by(gh_login=gh_login).first()
        if user:
            if user not in project.members and user != project.owner:
                project.members.append(user)
                db.session.commit()
            return redirect(url_for('.settings', id=project_id))
        else:
            flash('User with GitHub login "{}" was not found.'.format(gh_login),
                  'warning')
    return render_template(
        'projects/add-member.html', project=project, form=form)


@bp.route('/<int:project_id>/members/<int:user_id>/delete/', methods=['GET', 'POST'])
def delete_member(project_id, user_id):
    project = Project.query.get_or_404(project_id)
    user = project.members.filter_by(id=user_id).first_or_404()
    project.members.remove(user)
    db.session.commit()
    return redirect(url_for('.settings', id=project_id))
