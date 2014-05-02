import logging

from flask import (Response, current_app, render_template, redirect,
                   flash, request, url_for)
from flask.ext.login import current_user

from . import bp
from .forms import HookForm, MemberForm
from kozmic import db, perms
from kozmic.models import (MISSING_ID, Project, User, Membership, Hook,
                           Build, Job)
from kozmic.builds.tasks import restart_job


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


def get_project(id, for_management=True):
    project = Project.query.get_or_404(id)
    if for_management:
        permission_to_test = perms.manage_project(id)
    else:
        permission_to_test = perms.view_project(id)
    permission_to_test.test(http_exception=403)
    return project


@bp.route('/<int:id>/delete/', methods=('POST',))
def delete_project(id):
    project = Project.query.get_or_404(id)
    perms.delete_project(id).test(http_exception=403)

    ok_to_commit = project.delete()
    if ok_to_commit:
        db.session.commit()
        flash('Project "{}" has been successfully '
              'deleted.'.format(project.gh_full_name),
              'success')
        return redirect(url_for('.index'))
    else:
        db.session.rollback()
        flash('Something went wrong (probably there was a problem '
              'communicating with the GitHub API). Please try again later.',
              'warning')
        return redirect(url_for('.settings', id=project.id))


@bp.route('/<int:id>/history/')
def history(id):
    project = get_project(id, for_management=False)

    builds = project.builds.order_by(Build.id.desc())
    if not builds.first():
        return redirect(url_for('.settings', id=id))

    page = request.args.get('page', 1, type=int)
    pagination = builds.paginate(page, per_page=50)

    return render_template(
        'projects/history.html',
        project=project,
        pagination=pagination,
        builds=pagination.items)


@bp.route('/<int:project_id>/builds/<id>/')
def build(project_id, id):
    project = get_project(project_id, for_management=False)

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
    project = get_project(project_id, for_management=False)
    build = project.builds.filter_by(id=build_id).first_or_404()
    job = build.jobs.filter_by(id=id).first_or_404()

    return render_template(
        'projects/job.html',
        project=project,
        build=build,
        job=job)


@bp.route('/<int:project_id>/jobs/<int:id>/log/')
def job_log(project_id, id):
    project = get_project(project_id, for_management=False)
    job = project.builds.join(Job).filter(
        Job.id == id).with_entities(Job).first_or_404()
    return Response(job.stdout, mimetype='text/plain')


@bp.route('/<int:project_id>/job/<int:id>/restart/')
def job_restart(project_id, id):
    project = get_project(project_id, for_management=True)
    job = project.builds.join(Job).filter(
        Job.id == id).with_entities(Job).first_or_404()
    restart_job.delay(job.id)
    job.build.set_status('enqueued')
    db.session.commit()
    return redirect(url_for('.build', project_id=project.id, id=job.build.id))


@bp.route('/<int:id>/settings/')
def settings(id):
    project = get_project(id, for_management=False)
    members = project.members.join(Membership).with_entities(
        User, Membership.allows_management).all()
    kwargs = {
        'fqdn': current_app.config['SERVER_NAME'],
        'protocol': ('https' if current_app.config['KOZMIC_USE_HTTPS_FOR_BADGES']
                     else 'http'),
        'project_id': project.id,
        'project_full_name': project.gh_full_name,
    }
    example_badge_href = ('http://{fqdn}/projects/{project_id}/'
                          'builds/latest/?ref=master'.format(**kwargs))
    example_badge_src = ('{protocol}://{fqdn}/badges/{project_full_name}/'
                         'master'.format(**kwargs))
    return render_template(
        'projects/settings.html',
        project=project,
        members=members,
        is_current_user_a_manager=perms.manage_project(id).can(),
        can_current_user_delete_a_project=perms.delete_project(id).can(),
        example_badge_href=example_badge_href,
        example_badge_src=example_badge_src)


@bp.route('/<int:project_id>/hooks/ensure/', methods=('POST',))
def ensure_hooks(project_id):
    project = get_project(project_id, for_management=True)

    ok_to_commit = True
    for hook in project.hooks:
        ok_to_commit &= hook.ensure()
    if ok_to_commit:
        db.session.commit()
    else:
        db.session.rollback()
        flash('Something went wrong (probably there was a problem '
              'communicating with the GitHub API). Please try again later.',
              'warning')
    return redirect(url_for('.settings', id=project_id))


@bp.route('/<int:project_id>/hooks/add/', methods=('GET', 'POST'))
def add_hook(project_id):
    project = get_project(project_id, for_management=True)

    form = HookForm(request.form)
    if form.validate_on_submit():
        hook = Hook(project=project, gh_id=MISSING_ID)
        form.populate_obj(hook)
        db.session.add(hook)
        db.session.flush()  # Flush SQL to get `hook.id`
        ok_to_commit = hook.ensure()

        if ok_to_commit:
            db.session.commit()
        else:
            db.session.rollback()
            flash('Sorry, failed to create a hook. Please try again later.',
                  'warning')
        return redirect(url_for('.settings', id=project_id))
    else:
        return render_template(
            'projects/add-hook.html', project=project, form=form)


@bp.route('/<int:project_id>/hooks/<int:hook_id>/edit/', methods=('GET', 'POST'))
def edit_hook(project_id, hook_id):
    project = get_project(project_id, for_management=True)
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


@bp.route('/<int:project_id>/hooks/<int:hook_id>/delete/', methods=('POST',))
def delete_hook(project_id, hook_id):
    project = get_project(project_id, for_management=True)
    hook = project.hooks.filter_by(id=hook_id).first_or_404()

    ok_to_commit = hook.delete()
    if ok_to_commit:
        db.session.commit()
    else:
        db.session.rollback()
        flash('Something went wrong (probably there was a problem '
              'communicating with the GitHub API). Please try again later.',
              'warning')
    return redirect(url_for('.settings', id=project_id))


@bp.route('/<int:id>/memberships/sync/', methods=('POST',))
def sync_memberships(id):
    project = get_project(id, for_management=True)

    ok_to_commit = project.sync_memberships_with_github()
    if ok_to_commit:
        db.session.commit()
    else:
        db.session.rollback()
        flash('Something went wrong (probably there was a problem '
              'communicating with the GitHub API). Please try again later.',
              'warning')

    return redirect(url_for('.settings', id=id))
