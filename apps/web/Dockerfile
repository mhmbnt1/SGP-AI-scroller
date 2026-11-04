FROM node:22-alpine AS build
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml .npmrc ./
COPY packages/contracts ./packages/contracts
COPY apps/web ./apps/web
COPY apps/mobile/package.json ./apps/mobile/package.json
RUN CI=true pnpm install --frozen-lockfile --filter @focusfeed/web... --filter @focusfeed/contracts
RUN pnpm --filter @focusfeed/web build

FROM node:22-alpine AS run
RUN corepack enable && addgroup -S app && adduser -S app -G app
WORKDIR /repo
COPY --from=build --chown=app:app /repo ./
USER app
ENV NODE_ENV=production PORT=3000
EXPOSE 3000
CMD ["pnpm", "--filter", "@focusfeed/web", "start"]
