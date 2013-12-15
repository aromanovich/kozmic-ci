import hashlib
import datetime

import factory.alchemy

from kozmic.models import (db, User, Project, Hook, HookCall,
                           Build, Organization)


class Factory(factory.alchemy.SQLAlchemyModelFactory):
    FACTORY_SESSION = None
    ABSTRACT_FACTORY = True

    @classmethod
    def _create(cls, target_class, *args, **kwargs):
        obj = super(Factory, cls)._create(target_class, *args, **kwargs)
        cls.FACTORY_SESSION.commit()
        return obj


def setup(session):
    Factory.FACTORY_SESSION = session


def reset():
    BuildFactory.reset_sequence()
    ProjectFactory.reset_sequence()
    UserFactory.reset_sequence()


class UserFactory(Factory):
    FACTORY_FOR = User

    id = factory.Sequence(lambda n: n)
    gh_id = factory.Sequence(lambda n: n)
    gh_name = factory.Sequence(lambda n: u'User %d' % n)
    gh_login = factory.Sequence(lambda n: u'user_%d' % n)
    gh_avatar_url = factory.Sequence(lambda n: u'http://example.com/%d.png' % n)
    gh_access_token = 'token'


class UserRepositoryFactory(Factory):
    FACTORY_FOR = User.Repository

    id = factory.Sequence(lambda n: n)
    gh_id = factory.Sequence(lambda n: 1000 + n)
    gh_name = 'django'
    gh_full_name = 'johndoe/django'

    @factory.lazy_attribute
    def gh_clone_url(self):
        return 'git://github.com/{}.git'.format(self.gh_full_name)


class OrganizationFactory(Factory):
    FACTORY_FOR = Organization

    id = factory.Sequence(lambda n: n)
    gh_id = factory.Sequence(lambda n: n)
    gh_login = 'pyconru'
    gh_name = 'PyCon Russia'


class OrganizationRepositoryFactory(Factory):
    FACTORY_FOR = Organization.Repository

    id = factory.Sequence(lambda n: n)
    gh_id = factory.Sequence(lambda n: 2000 + n)
    gh_name = 'django'
    gh_full_name = 'johndoe/django'

    @factory.lazy_attribute
    def gh_clone_url(self):
        return 'git://github.com/{}.git'.format(self.gh_full_name)


class ProjectFactory(Factory):
    FACTORY_FOR = Project

    id = factory.Sequence(lambda n: n)
    gh_id = factory.Sequence(lambda n: n)
    gh_name = factory.Sequence(lambda n: u'project_%d' % n)
    gh_full_name = factory.Sequence(lambda n: u'Project %d' % n)
    gh_login = factory.Sequence(lambda n: u'project_%d' % n)
    gh_clone_url = factory.Sequence(lambda n: u'git://example.com/%d.git' % n)
    gh_key_id = factory.Sequence(lambda n: n)
    rsa_public_key = factory.Sequence(lambda n: str(n))
    rsa_private_key = factory.Sequence(lambda n: str(n) + '.pub')


class BuildFactory(Factory):
    FACTORY_FOR = Build

    id = factory.Sequence(lambda n: n)
    gh_commit_author = 'aromanovich'
    gh_commit_message = 'ok'
    gh_commit_ref = 'master'
    status = 'enqueued'

    @factory.lazy_attribute
    def number(self):
        return len(self.project.builds.all()) + 1

    @factory.lazy_attribute
    def created_at(self):
        days = self.number
        return (datetime.datetime(2013, 11, 8, 20, 10, 25) +
                datetime.timedelta(days=days))

    @factory.lazy_attribute
    def gh_commit_sha(self):
        digest = hashlib.sha1()
        digest.update(str(self.id))
        return digest.hexdigest()


class HookFactory(Factory):
    FACTORY_FOR = Hook

    id = factory.Sequence(lambda n: n)
    gh_id = factory.Sequence(lambda n: n)
    title = factory.Sequence(lambda n: u'Hook %d' % n)
    build_script = './kozmic.sh'
    docker_image = 'ubuntu'


class HookCallFactory(Factory):
    FACTORY_FOR = HookCall

    id = factory.Sequence(lambda n: n)
    gh_payload = '{}'
