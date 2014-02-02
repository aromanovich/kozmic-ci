"""
Tailer
======
An WSGI-application that watches a Redis pub/sub channel and streams it's
content to a websocket.

The application exposes only one endpoint: `/<channel-name>/`.

It does the following:

1. Retrieves a list of strings stored at the `channel-name` *key* and sends
   it to the websocket;
2. Subscribes to the `channel-name` pub/sub *channel* and streams it's content
   to the websocket while the `channel-name` *key* exists in Redis database.

The implementation heavily rely on the uwsgi functionality. The app can be started
using the following command string::

    REDIS_HOST=127.0.0.1 \\
    REDIS_PORT=6379 \\
    REDIS_DATABASE=0 \\
    uwsgi --http-socket :9090 --gevent 100 --module tailer:app --gevent-monkey-patch

Do not use ``--http :9090``, because it breaks websockets ping/pong.
"""
import os
import re
import json

import uwsgi
import redis
import gevent.select
from werkzeug.utils import import_string


if 'KOZMIC_CONFIG' in os.environ:
    config = import_string(os.environ['KOZMIC_CONFIG'])
    redis_host = config.KOZMIC_REDIS_HOST
    redis_port = config.KOZMIC_REDIS_PORT
    redis_db = config.KOZMIC_REDIS_DATABASE
else:
    redis_host = os.environ['REDIS_HOST']
    redis_port = os.environ['REDIS_PORT']
    redis_db = os.environ['REDIS_DATABASE']

redis = redis.StrictRedis(host=redis_host, port=redis_port, db=redis_db)


def send_message(type, content):
    uwsgi.websocket_send(json.dumps({
        'type': type,
        'content': content,
    }))


def app(environ, start_response):
    match = re.match('/(?P<job_id>.+)/', environ['PATH_INFO'])
    if not match:
        start_response('404', [('Content-Type', 'text/plain')])
    job_id = match.group('job_id')

    uwsgi.websocket_handshake(environ['HTTP_SEC_WEBSOCKET_KEY'],
                              environ.get('HTTP_ORIGIN', ''))
    
    # Emit the backlog of messages
    lines = r.lrange(job_id, 0, -1)
    send_message('message', ''.join(lines))

    channel = redis.pubsub()
    channel.subscribe(job_id)
    channel_socket_fd = channel.connection._sock.fileno()
    websocket_fd = uwsgi.connection_fd()

    while True:
        rlist, _, _ = gevent.select.select(
            [channel_socket_fd, websocket_fd], [], [], 5.0)
        if rlist:
            for fd in rlist:
                if fd == channel_socket_fd:
                    message = channel.parse_response()
                    # See http://redis.io/topics/pubsub for format of `message`
                    if message[0] == 'message':
                        send_message('message', message[2])
                elif fd == websocket_fd:
                    # Let uwsgi do it's job to receive pong and send ping
                    uwsgi.websocket_recv_nb()
        else:
            # Have not heard from the channel and the client in 5 seconds...
            try:
                # Check if the client is still here by sending ping
                # (`websocket_recv` sends ping implicitly,
                # `websocket_recv_nb` -- non-blocking variant of it)
                uwsgi.websocket_recv_nb()
            except IOError:
                break
            # Check if the job is still ongoing
            if not redis.exists(job_id):
                send_message('status', 'finished')
                break
    return ''
