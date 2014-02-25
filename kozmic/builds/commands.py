import logging
import collections
import datetime as dt

import flask

from kozmic import docker


logger = logging.getLogger(__name__)


def clean_dependencies_cache(verbose=True):
    images_by_projects = collections.defaultdict(list)
    limit = flask.current_app.config['KOZMIC_CACHED_IMAGES_LIMIT']

    for image_data in docker.images():
        created_at = image_data['Created']

        for repo_tag in image_data['RepoTags']:
            if not repo_tag.startswith('kozmic-cache/'):
                continue

            try:
                repository, tag = repo_tag.split(':')
            except ValueError:
                continue

            try:
                project_id = int(tag)
            except ValueError:
                continue

            images_by_projects[project_id].append((created_at, image_data['Id']))
            break

    for project_id, timestamped_images in images_by_projects.iteritems():
        images_to_remove = [image for _, image in
                            sorted(timestamped_images)[:-limit]]
        for image in images_to_remove:
            docker.remove_image(image)
            logger.info('Removed %s', image)
