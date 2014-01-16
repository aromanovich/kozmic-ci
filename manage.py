#!/usr/bin/env python
# coding: utf-8
import os

from flask.ext.script import Manager
from flask.ext.migrate import MigrateCommand

import kozmic


manager = Manager(kozmic.create_app)
manager.add_command('db', MigrateCommand)


if __name__ == '__main__':
    if 'KOZMIC_CONFIG' not in os.environ:
        print('Did you forget to set KOZMIC_CONFIG environment variable?')
        exit(1)
    manager.run()
