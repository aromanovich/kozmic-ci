#!/bin/bash
echo "$CONFIG" > /src/kozmic/config_local.py
export KOZMIC_CONFIG=kozmic.config_local.Config 
cd /src
./manage.py db upgrade
supervisord -c /etc/supervisor.conf
