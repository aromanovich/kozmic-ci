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
