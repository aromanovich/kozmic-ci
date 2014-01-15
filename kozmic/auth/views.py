import github3
from flask import render_template, current_app, redirect, url_for
from flask.ext.login import login_user, logout_user, login_required

from kozmic import db
from kozmic.models import User
from . import bp


@bp.route('/_auth/auth-callback/')
@bp.github_oauth_app.authorized_handler
def auth_callback(response):
    access_token = response['access_token']
    gh = github3.login(token=access_token)
    gh_user = gh.user()
    user = (User.query.filter_by(gh_login=gh_user.login).first() or
            User(gh_id=gh_user.id,
                 gh_name=gh_user.name,
                 gh_login=gh_user.login,
                 gh_avatar_url=gh_user.avatar_url,
                 email=gh_user.email))
    user.gh_access_token = access_token
    db.session.add(user)
    db.session.commit()
    login_user(user, remember=True)
    return redirect(url_for('projects.index'))


@bp.route('/_auth/')
def auth():
    callback_url = url_for('.auth_callback', _external=True)
    return bp.github_oauth_app.authorize(callback=callback_url)


@bp.route('/login/')
def login():
    return render_template('auth/login.html')


@bp.route('/logout/')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))
