from flask import current_app, request, render_template, redirect, url_for, flash
from flask.ext.login import current_user

from kozmic import db
from . import bp
from .forms import SettingsForm


@bp.route('/settings/', methods=('GET', 'POST'))
def settings():
    form = SettingsForm(request.form, obj=current_user)
    if form.validate_on_submit():
        form.populate_obj(current_user)
        db.session.add(current_user)
        db.session.commit()
        flash('Your settings have been saved.', category='success')
        return redirect(url_for('.settings'))
    return render_template('accounts/settings.html', form=form)


@bp.route('/memberships/sync/', methods=('POST',))
def sync_memberships():
    ok_to_commit = current_user.sync_memberships_with_github()

    if ok_to_commit:
        db.session.commit()
    else:
        db.session.rollback()
        flash('Something went wrong (probably there was a problem '
              'communicating with the GitHub API). Please try again later.',
              'warning')

    return redirect(request.referrer or url_for('projects.index'))
