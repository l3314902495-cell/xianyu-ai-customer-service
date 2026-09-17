FROM node:22-alpine AS deps
RUN corepack enable
WORKDIR /workspace
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile
FROM deps AS build
ENV DOCKER_BUILD=1
COPY apps/web apps/web
RUN mkdir -p apps/web/public
RUN pnpm --filter @xianyu/web build
FROM node:22-alpine
WORKDIR /app
COPY --from=build /workspace/apps/web/.next/standalone ./
COPY --from=build /workspace/apps/web/.next/static ./apps/web/.next/static
COPY --from=build /workspace/apps/web/public ./apps/web/public
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
