# Offline fallback for source-only backend changes. Dependencies and migrations
# remain in the existing image; the current application package is replaced.
FROM wo-xi-api:latest
WORKDIR /app
COPY apps/api/app ./app
