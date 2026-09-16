# Next.js inspector PWA + dashboard.
#
# Development target by default (compose overrides the command with `npm run
# dev`). The `runner` stage below is the production image: standalone output,
# non-root, no source or dev dependencies.

FROM node:22-bookworm-slim AS deps
WORKDIR /app/apps/web
COPY apps/web/package.json apps/web/package-lock.json* ./
# `npm ci` requires a lockfile; fall back to `install` on a first build where
# one has not been generated yet.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

FROM node:22-bookworm-slim AS dev
WORKDIR /app/apps/web
ENV NODE_ENV=development
COPY --from=deps /app/apps/web/node_modules ./node_modules
COPY apps/web ./
EXPOSE 3000
CMD ["npm", "run", "dev"]

FROM node:22-bookworm-slim AS builder
WORKDIR /app/apps/web
COPY --from=deps /app/apps/web/node_modules ./node_modules
COPY apps/web ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-bookworm-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

RUN groupadd --system --gid 10001 nodejs \
    && useradd --system --uid 10001 --gid nodejs nextjs

COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/public ./public

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
