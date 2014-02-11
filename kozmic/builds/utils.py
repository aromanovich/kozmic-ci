from kozmic import docker


def does_docker_image_exist(image, tag='latest'):
    return bool(get_docker_image_id(image, tag))


def get_docker_image_id(image, tag):
    for image_data in docker.images(image):
        for repo_tag in image_data['RepoTags']:
            if repo_tag == ':'.join((image, tag)):
                return image_data['Id']
    return None
