FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml poetry.lock ./
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry install --only main --no-interaction --no-root

COPY hort/ ./hort/
COPY run.py ./

# Embed build version — set via --build-arg or defaults to timestamp
ARG BUILD_VERSION=dev
ARG BUILD_TIME=""
RUN python -c "import json, datetime; json.dump({'version': '${BUILD_VERSION}', 'build_time': '${BUILD_TIME}' or datetime.datetime.utcnow().isoformat() + 'Z'}, open('/app/build_info.json', 'w'))"

COPY hort/access/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV ACCESS_SESSION_SECRET=""
EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "hort.access.server", "--port", "8080", "--store", "/data/hort-access.json"]
