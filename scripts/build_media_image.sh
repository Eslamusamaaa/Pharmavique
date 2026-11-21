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

# The Dockerfile copies the pictures layer by layer, by register-number prefix. Check that no picture
# file fell between the patterns: the container must copy as many files as the folder holds.
EXPECTED="$(find data/media/images -type f | wc -l | tr -d ' ')"
VOLUME="media-build-check-$$"
trap 'docker volume rm -f "$VOLUME" >/dev/null 2>&1 || true' EXIT
GOT="$(docker run --rm -v "$VOLUME:/target" "$IMAGE:$TAG" | sed -n 's/^copied \([0-9]*\) picture files$/\1/p')"
if [ "$GOT" != "$EXPECTED" ]; then
  echo "picture files missing from the image: folder has $EXPECTED, image has ${GOT:-?}; add a COPY pattern to docker/media/Dockerfile" >&2
  exit 1
fi
echo "image holds all $EXPECTED picture files"

if [ "${1:-}" = "--push" ]; then
  docker push "$IMAGE:$TAG"
  docker push "$IMAGE:latest"
fi
docker image ls "$IMAGE"
