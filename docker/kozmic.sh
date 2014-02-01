#!/bin/bash
echo "$CONFIG" > /src/kozmic/config_local.py
export KOZMIC_CONFIG=kozmic.config_local.Config 
echo '{}' > /.dockercfg  # due to the docker-py==0.2.2 peculiarity
cd /src
./manage.py db upgrade
supervisord -c /etc/supervisor.conf
