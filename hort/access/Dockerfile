FROM --platform=linux/amd64 python:3.13-slim

WORKDIR /app

COPY pyproject.toml poetry.lock ./
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry install --only main --no-interaction --no-root

COPY hort/ ./hort/
COPY run.py ./

ARG ADMIN_PASSWORD=ChangeMe123!
RUN python -c "from hort.access.store import FileStore; from hort.access.auth import hash_password; s = FileStore('/app/hort-access.json'); s.create_user('admin', hash_password('${ADMIN_PASSWORD}'), 'Administrator')"

ENV ACCESS_SESSION_SECRET=""
EXPOSE 8080

CMD ["python", "-m", "hort.access.server", "--port", "8080", "--store", "/app/hort-access.json"]
