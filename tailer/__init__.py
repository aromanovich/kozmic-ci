"""
Tailer
======
An WSGI-application that watches a Redis pub/sub channel and streams it's
content to a websocket.

The application exposes only one endpoint: `/<channel-name>/`.

Once there is a connection, it does the following:

1. Retrieves a list of strings stored at the `channel-name` *key* and sends
   it to the websocket;
2. Subscribes to the `channel-name` pub/sub *channel* and sends it's content
   to the websocket while the `channel-name` *key* exists in Redis database.

The implementation heavily rely on uwsgi functionality. The app can be started
using the following command string::

    TAILER_REDIS_HOST=127.0.0.1 \\
    TAILER_REDIS_PORT=6379 \\
    TAILER_REDIS_DATABASE=0 \\
    uwsgi --http-socket :9090 --gevent 100 --module tailer:app --gevent-monkey-patch
"""
import os
import re
import json

import uwsgi
import redis
import gevent.select


def send_message(type, content):
    uwsgi.websocket_send(json.dumps({
        'type': type,
        'content': content,
    }))


def app(environ, start_response):
    match = re.match('/(?P<task_uuid>.+)/', environ['PATH_INFO'])
    if not match:
        start_response('404', [('Content-Type', 'text/plain')])
    task_uuid = match.group('task_uuid')

    r = redis.StrictRedis(
        host=os.environ['TAILER_REDIS_HOST'],
        port=os.environ['TAILER_REDIS_PORT'],
        db=os.environ['TAILER_REDIS_DATABASE'])

    uwsgi.websocket_handshake(environ['HTTP_SEC_WEBSOCKET_KEY'],
                              environ.get('HTTP_ORIGIN', ''))
    
    # Emit the backlog of messages
    lines = r.lrange(task_uuid, 0, -1)
    send_message('message', ''.join(lines))

    channel = r.pubsub()
    channel.subscribe(task_uuid)
    channel_socket_fd = channel.connection._sock.fileno()

    while True:
        # Temporary solution: select timeout has to be less than 3 seconds
        # because uwsgi imposes hard-coded timeout for wating pong:
        # https://github.com/unbit/uwsgi/blob/master/core/websockets.c#L409
        rlist, _, _ = gevent.select.select([channel_socket_fd], [], [], 2.0)
        if rlist:
            message = channel.parse_response()
            # See http://redis.io/topics/pubsub for format of `message`
            if message[0] == 'message':
                send_message('message', message[2])
        else:
            # Have not heard from channel in 5 seconds...
            try:
                # Check if the client is still here by sending ping
                # (`websocket_recv` sends ping implicitly,
                # `websocket_recv_nb` -- non-blocking variant of it)
                uwsgi.websocket_recv_nb()
            except IOError:
                break
            # Check if the build is still ongoing
            if not r.exists(task_uuid):
                send_message('status', 'finished')
                break
    return ''
