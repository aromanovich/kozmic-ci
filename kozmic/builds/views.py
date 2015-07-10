# coding: utf-8

import json
import re

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
        ref = payload.get('ref')  # ref looks like "refs/heads/master"
        if not ref or not ref.startswith('refs/heads/'):
            return None
        prefix_length = len('refs/heads/')
        ref = ref[prefix_length:]
        sha = payload.get('head_commit', {}).get('id')
        if not sha:
            return None
        return ref, sha

    elif action in ('opened', 'synchronize'):
        # See `tests.func_fixtures.PULL_REQUEST_HOOK_CALL_DATA` for payload
        gh_pull = github3.pulls.PullRequest(payload.get('pull_request', {}))
        try:
            return gh_pull.head.ref, gh_pull.head.sha
        except:
            return None
    else:
        return None


@csrf.exempt
@bp.route('/_hooks/hook/<int:id>/', methods=('POST',))
def hook(id):
    def need_skip_build(gh_commit, payload):
        search_string = gh_commit.message

        if 'pull_request' in payload:
            pr_title = payload['pull_request']['title'] or ''
            pr_body = payload['pull_request']['body'] or ''
            search_string += pr_title + pr_body

        skip_regexp = re.compile('\[ci\s+skip\]|\[skip\s+ci\]|skip_ci|ci_skip', re.IGNORECASE)
        if skip_regexp.search(search_string):
            return True
        else:
            return False

    hook = Hook.query.get_or_404(id)
    payload = json.loads(request.data)

    if set(payload.keys()) == {'zen', 'hook_id'}:
        # http://developer.github.com/webhooks/#ping-event
        if hook.gh_id != payload['hook_id']:
            return 'Wrong hook URL', 400
        else:
            return 'OK'

    ref_and_sha = get_ref_and_sha(payload)
    if not ref_and_sha:
        return 'Failed to fetch ref and commit from payload', 400
    ref, sha = ref_and_sha

    gh_commit = hook.project.gh.git_commit(sha)

    # Skip build if message contains si skip pattern
    if need_skip_build(gh_commit, payload):
        return 'OK'

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
