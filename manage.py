#!/usr/bin/env python
# coding: utf-8
from flask.ext.script import Manager
from flask.ext.migrate import Migrate, MigrateCommand

import kozmic


manager = Manager(kozmic.create_app)
manager.add_command('db', MigrateCommand)


if __name__ == '__main__':
    manager.run()
