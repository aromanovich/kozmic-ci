"""
kozmic.perms
~~~~~~~~~~~~
"""
from functools import partial

from flask.ext.principal import Permission, RoleNeed, Need


#: Project owner need
project_owner = partial(Need, 'project_owner')
#: Project manager need
project_manager = partial(Need, 'project_manager')
#: Project member need
project_member = partial(Need, 'project_member')


def delete_project(id):
    """Returns a :class:`Permission` to delete the project
    identified by ``id``.
    """
    return Permission(project_owner(id))


def manage_project(id):
    """Returns a :class:`Permission` to manage the project
    identified by ``id``.
    """
    return Permission(project_manager(id), project_owner(id))


def view_project(id):
    """Returns a :class:`Permission` to view the project
    identified by ``id``.
    """
    return Permission(project_member(id)) & manage_project(id)
