FROM ubuntu:12.04
MAINTAINER Anton Romanovich <anthony.romanovich@gmail.com>

RUN echo "deb http://archive.ubuntu.com/ubuntu precise universe" > /etc/apt/sources.list.d/universe.list
RUN echo "deb http://get.docker.io/ubuntu docker main" > /etc/apt/sources.list.d/docker.list
RUN apt-get install -y curl
RUN curl -s https://get.docker.io/gpg | apt-key add -
RUN apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 6E63A3B44CF61F28A8A477DE5563540C431533D8  # syslog
RUN echo "deb http://ppa.launchpad.net/tmortensen/rsyslogv7/ubuntu precise main" >> /etc/apt/sources.list
RUN apt-get update -qq
RUN DEBIAN_FRONTEND=noninteractive apt-get install -y python-apt ca-certificates \
    python-pip python-dev libev4 libev-dev libssh-dev libpcre3-dev rsyslog \
    cron mysql-server redis-server git lxc-docker-0.10.0
RUN pip install supervisor
RUN useradd -m -d /home/kozmic -G docker -s /bin/bash kozmic
RUN git clone https://github.com/aromanovich/kozmic-ci.git /src/
RUN pip install -r /src/requirements/kozmic.txt
RUN pip install -r /src/requirements/tailer.txt

ADD ./files/rsyslog.conf /etc/rsyslog.d/50-default.conf
ADD ./files/rsyslog-logrotate /etc/logrotate.d/rsyslog
ADD ./files/supervisor.conf /etc/supervisor.conf
ADD ./files/kozmic-uwsgi.ini /etc/kozmic-uwsgi.ini
ADD ./files/tailer-uwsgi.ini /etc/tailer-uwsgi.ini
ADD ./files/wrapped-docker /bin/wrapped-docker
ADD ./files/crontab /etc/crontab
ADD ./files/config.py-docker /config.py-docker
ADD ./files/run.sh /run.sh
RUN chmod +x /bin/wrapped-docker /run.sh && \
    chown root /etc/crontab && \
    chmod 644 /etc/crontab

VOLUME /var/lib/docker
VOLUME /var/lib/mysql

ENTRYPOINT ["/run.sh"]
