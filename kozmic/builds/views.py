import json

import github3
import sqlalchemy
from flask import request, redirect, url_for

from kozmic import db, csrf
from kozmic.models import Project, Build, Hook, HookCall
from . import bp, tasks


def get_ref_and_sha(payload):
    action = payload.get('action')

    if action is None:
        # See `tests.func_fixtures.PUSH_HOOK_CALL_DATA` for payload
        ref = payload['ref']  # ref looks like "refs/heads/master"
        if not ref.startswith('refs/heads/'):
            return None
        prefix_length = len('refs/heads/')
        ref = ref[prefix_length:]
        sha = payload['head_commit']['id']
        return ref, sha

    elif action in ('opened', 'synchronize'):
        # See `tests.func_fixtures.PULL_REQUEST_HOOK_CALL_DATA` for payload
        gh_pull = github3.pulls.PullRequest(payload['pull_request'])
        return gh_pull.head.ref, gh_pull.head.sha

    else:
        return None


@csrf.exempt
@bp.route('/_hooks/hook/<int:id>/', methods=('POST',))
def hook(id):
    payload = json.loads(request.data)
    ref_and_sha = get_ref_and_sha(payload)
    if not ref_and_sha:
        return 'OK'
    ref, sha = ref_and_sha

    hook = Hook.query.get_or_404(id)
    gh_commit = hook.project.gh.git_commit(sha)

    build = hook.project.builds.filter(
        Build.gh_commit_ref == ref,
        Build.gh_commit_sha == gh_commit.sha).first()

    if not build:
        build = Build(
            project=hook.project,
            status='enqueued',
            gh_commit_ref=ref,
            gh_commit_sha=gh_commit.sha,
            gh_commit_author=gh_commit.author['name'],
            gh_commit_message=gh_commit.message)
        build.calculate_number()
        db.session.add(build)

    hook_call = HookCall(
        hook=hook,
        build=build,
        gh_payload=payload)
    db.session.add(hook_call)

    try:
        db.session.commit()
    except sqlalchemy.exc.IntegrityError:
        # Commit may fail due to "unique_ref_and_sha_within_project"
        # constraint on Build or "unique_hook_call_within_build" on
        # HookCall. It means that GitHub called this hook twice
        # (for example, on push and pull request sync events)
        # at the same time and Build and HookCall has been just
        # committed by another transaction.
        db.session.rollback()
        return 'OK'

    tasks.do_job.delay(hook_call_id=hook_call.id)
    return 'OK'


@bp.route('/badges/<gh_login>/<gh_name>/<ref>')
def badge(gh_login, gh_name, ref):
    project = Project.query.filter_by(
        gh_login=gh_login, gh_name=gh_name).first_or_404()
    build = project.get_latest_build(ref=ref)
    badge = build and build.status or 'success'
    response = redirect(url_for(
        'static',
        filename='img/badges/{}.png'.format(badge),
        _external=True,
        # Use https so that GitHub does not cache images served from HTTPS
        _scheme='https'))
    response.status_code = 307
    return response
