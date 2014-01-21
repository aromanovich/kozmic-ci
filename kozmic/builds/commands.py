import datetime as dt

import docker


def clean_dependencies_cache():
    d = docker.Client()
    for image in d.images():
        repository = image['Repository']
        if not repository.startswith('kozmic-cache/'):
            continue

        created_at = image['Created']
        if (dt.datetime.utcnow() - dt.datetime.fromtimestamp(created_at) >
                dt.timedelta(days=7)):
            d.remove_image(repository)
            print('Removed {}'.format(repository))
