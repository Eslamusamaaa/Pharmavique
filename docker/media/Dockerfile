# Data-only image with the product picture files (data/media/images, about 700 MB).
#
# The pictures are not kept in git: they ship as this image. At start it copies the files into the
# volume the API reads, then exits. Build with scripts/build_media_image.sh (the build context is
# the images folder itself, so nothing else from the repository is sent to Docker).
FROM busybox:1.37

COPY . /images

CMD ["sh", "-c", "mkdir -p /target && cp -a /images/. /target/ && echo \"copied $(find /target -type f | wc -l) picture files\""]
