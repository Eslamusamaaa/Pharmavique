# Data-only image with the product picture files (data/media/images, about 700 MB).
#
# The pictures are not kept in git: they ship as this image. At start it copies the files into the
# volume the API reads, then exits. Build with scripts/build_media_image.sh (the build context is
# the images folder itself, so nothing else from the repository is sent to Docker).
#
# The pictures are split over many layers (about 20 to 60 MB each, by the first characters of the
# register number) instead of one 700 MB layer. A push that is cut halfway then only repeats the
# layer that was in flight, and each upload is a short burst. scripts/build_media_image.sh checks
# that every picture file ended up in some layer; add a pattern here if it reports a gap.
FROM busybox:1.37

COPY --parents products/SA/0[0-3]* /images/
COPY --parents products/SA/0[4-5]* /images/
COPY --parents products/SA/0[6-7]* /images/
COPY --parents products/SA/08* /images/
COPY --parents products/SA/09* /images/
COPY --parents products/SA/10* /images/
COPY --parents products/SA/11* /images/
COPY --parents products/SA/12* /images/
COPY --parents products/SA/13* /images/
COPY --parents products/SA/14* /images/
COPY --parents products/SA/15* /images/
COPY --parents products/SA/16* /images/
COPY --parents products/SA/17* /images/
COPY --parents products/SA/18* /images/
COPY --parents products/SA/19* /images/
COPY --parents products/SA/20* /images/
COPY --parents products/SA/21* /images/
COPY --parents products/SA/22* /images/
COPY --parents products/SA/23* /images/
COPY --parents products/SA/24* /images/
COPY --parents products/SA/25* /images/
COPY --parents products/SA/26* /images/
COPY --parents products/SA/27* /images/
COPY --parents products/SA/28* /images/
COPY --parents products/SA/29* /images/
COPY --parents products/SA/[3-9]* /images/
COPY --parents products/SA/[1-2]-* /images/
COPY --parents products/SA/H* /images/

CMD ["sh", "-c", "mkdir -p /target && cp -a /images/. /target/ && echo \"copied $(find /target -type f | wc -l) picture files\""]
