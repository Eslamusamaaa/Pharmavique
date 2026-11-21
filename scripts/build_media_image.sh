#!/usr/bin/env bash
# Build the data-only image with the product pictures, and optionally publish it to GitHub's
# container registry. The pictures are not in git (see docker/media/Dockerfile).
#
#   bash scripts/build_media_image.sh            # build ghcr.io/eslamusamaaa/pharmavique-media:<date> and :latest
#   bash scripts/build_media_image.sh --push     # also push both tags (needs: gh auth refresh -s write:packages,
#                                                #   then: gh auth token | docker login ghcr.io -u <user> --password-stdin)
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE="ghcr.io/eslamusamaaa/pharmavique-media"
TAG="$(date +%Y%m%d)"
test -d data/media/images || { echo "data/media/images not found: run the picture commands or pull the image first"; exit 1; }
docker build -f docker/media/Dockerfile -t "$IMAGE:$TAG" -t "$IMAGE:latest" data/media/images
if [ "${1:-}" = "--push" ]; then
  docker push "$IMAGE:$TAG"
  docker push "$IMAGE:latest"
fi
docker image ls "$IMAGE"
