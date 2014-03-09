#!/bin/bash
set -e

cd /src

echo "Filling the configuration file..."
config=$(</config.py-docker);
config="$config\n    DEBUG = ${DEBUG:-False}"
config="$config\n    SECRET_KEY = '$SECRET_KEY'"
config="$config\n    KOZMIC_GITHUB_CLIENT_ID = '$GITHUB_CLIENT_ID'"
config="$config\n    KOZMIC_GITHUB_CLIENT_SECRET = '$GITHUB_CLIENT_SECRET'"
config="$config\n    SERVER_NAME = '$SERVER_NAME'"
config="$config\n    SESSION_COOKIE_DOMAIN = '$SERVER_NAME'"
config="$config\n    TAILER_URL_TEMPLATE = 'ws://$SERVER_NAME:8080/{job_id}/'"
echo -e "$config" > ./kozmic/config_local.py

mkdir -p /var/log/mysql
mysql_install_db

echo "Starting MySQL server..."
mysqld_safe > /dev/null 2>&1 &
sleep 5
mysql -u root -e "CREATE DATABASE IF NOT EXISTS kozmic CHARACTER SET utf8 COLLATE utf8_unicode_ci;"
mysql -u root -e "GRANT ALL PRIVILEGES ON kozmic.* TO kozmic@localhost;"

echo "Running database migrations..."
KOZMIC_CONFIG=kozmic.config_local.Config ./manage.py db upgrade

echo "Stopping MySQL server..."
mysqladmin -uroot shutdown

KOZMIC_CONFIG=kozmic.config_local.Config \
WORKER_CONCURRENCY=${WORKER_CONCURRENCY:-3} \
supervisord -c /etc/supervisor.conf
