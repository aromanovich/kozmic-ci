import json

import github3
from flask import request

from kozmic import db, csrf
from kozmic.models import Build, Hook, HookCall
from . import bp, tasks


@csrf.exempt
@bp.route('/_hooks/hook/<int:id>/', methods=['POST'])  # XXX
def hook(id):
    payload = json.loads(request.data)

    action = payload.get('action')
    if action not in ('opened', 'synchronize'):
        return 'Not interested, sorry.'

    gh_pull = github3.pulls.PullRequest(payload['pull_request'])

    hook = Hook.query.get_or_404(id)
    hook_call = HookCall(gh_payload=payload)
    hook.calls.append(hook_call)

    gh_commit = hook.project.gh.git_commit(gh_pull.head.sha)

    build = (
        Build.query.filter(Build.gh_commit_sha == gh_commit.sha).first() or
        Build(project=hook.project,
              status='enqueued',
              gh_commit_sha=gh_commit.sha,
              gh_commit_author=gh_commit.author['name'],
              gh_commit_message=gh_commit.message))
    build.calculate_number()
    db.session.add(build)
    db.session.commit()

    tasks.do_build.delay(build_id=build.id, hook_call_id=hook_call.id)

    return 'Thanks!'
