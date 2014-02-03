This directory contains a Dockerfile and it's auxiliary files for building
a Kozmic CI Docker image.

```
docker run -e=WORKER_CONCURRENCY=1 \
           -e=CONFIG="`cat ./config.py-docker`" \
           -p=80:80 -p=8080:8080 \
           -v=/path/to/host/directory/:/var/log/ -privileged -d <image> /run.sh
```
