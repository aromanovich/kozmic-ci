import collections
import datetime as dt

import flask

from kozmic import docker


def clean_dependencies_cache():
    images_by_projects = collections.defaultdict(list)
    limit = flask.current_app.config['KOZMIC_CACHED_IMAGES_LIMIT']

    for image in docker.images():
        repository = image['Repository']
        created_at = image['Created']
        tag = image['Tag']

        if not repository.startswith('kozmic-cache/'):
            continue

        try:
            project_id = int(tag)
        except ValueError:
            continue

        images_by_projects[project_id].append((created_at, repository))

    for project_id, timestamped_images in images_by_projects.iteritems():
        images_to_remove = [image for _, image in
                            sorted(timestamped_images)[:-limit]]
        for image in images_to_remove:
            docker.remove_image(image)
            print('Removed {}'.format(image))
