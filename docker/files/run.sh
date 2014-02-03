#!/bin/bash
set -e
set -x

cd /src
echo "$CONFIG" > ./kozmic/config_local.py
KOZMIC_CONFIG=kozmic.config_local.Config ./manage.py db upgrade
KOZMIC_CONFIG=kozmic.config_local.Config supervisord -c /etc/supervisor.conf
