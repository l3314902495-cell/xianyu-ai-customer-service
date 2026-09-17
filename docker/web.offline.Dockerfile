# Offline fallback: reuse the already-installed runtime image and replace only
# the compiled Next.js application. This avoids pulling node:22-alpine when the
# Docker registry is temporarily unreachable.
FROM wo-xi-web:latest
WORKDIR /app
COPY apps/web/.next/server ./apps/web/.next/server
COPY apps/web/.next/static ./apps/web/.next/static
COPY apps/web/.next/*.json ./apps/web/.next/
COPY apps/web/.next/BUILD_ID ./apps/web/.next/BUILD_ID
COPY apps/web/.next/trace ./apps/web/.next/trace
