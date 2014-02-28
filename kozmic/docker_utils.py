from . import docker


def does_docker_image_exist(image, tag='latest'):
    return bool(get_docker_image_id(image, tag=tag))


def get_docker_image_id(image, tag='latest'):
    for image_data in docker.images(image):
        for repo_tag in image_data['RepoTags']:
            if repo_tag == ':'.join((image, tag)):
                return image_data['Id']
    return None
