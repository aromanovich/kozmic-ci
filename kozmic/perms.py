from functools import partial

from flask.ext.principal import Permission, RoleNeed, Need


project_owner = partial(Need, 'project_owner')
project_manager = partial(Need, 'project_manager')
project_member = partial(Need, 'project_member')


def manage_project(id):
    return Permission(project_manager(id), project_owner(id))


def view_project(id):
    return Permission(project_member(id)) & manage_project(id)
