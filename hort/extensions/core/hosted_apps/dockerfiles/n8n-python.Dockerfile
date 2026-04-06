FROM n8nio/n8n:latest AS base

# The hardened Alpine image strips apk. Use a multi-stage build
# to install Python 3.14 from a regular Alpine edge image.
FROM alpine:edge AS python-builder
RUN apk add --no-cache python3~=3.14

FROM base
COPY --from=python-builder /usr/bin/python3 /usr/bin/python3
COPY --from=python-builder /usr/lib/python3.14/ /usr/lib/python3.14/
COPY --from=python-builder /usr/lib/libpython3* /usr/lib/
USER root
RUN ln -sf /usr/bin/python3 /usr/bin/python
USER node
