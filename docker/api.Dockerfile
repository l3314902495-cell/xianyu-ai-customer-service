FROM python:3.12-slim
WORKDIR /app
COPY apps/api/pyproject.toml apps/api/README.md ./
COPY apps/api/app ./app
RUN pip install --no-cache-dir --retries 10 --timeout 120 .
COPY apps/api/alembic.ini ./
COPY apps/api/alembic ./alembic
EXPOSE 8000
