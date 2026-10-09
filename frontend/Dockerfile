# syntax=docker/dockerfile:1

# --- Build ------------------------------------------------------------------
FROM node:24.21.0-alpine AS build
ENV NG_CLI_ANALYTICS=false
WORKDIR /build
COPY package.json package-lock.json ./
# npm 11 runs no dependency install scripts unless allowed. None is needed:
# esbuild and lmdb ship prebuilt binaries as optional packages.
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund --ignore-scripts
COPY . .
RUN npx ng build

# --- Runtime ----------------------------------------------------------------
# The unprivileged variant runs as the nginx user and listens on 8080.
FROM nginxinc/nginx-unprivileged:1.31.6-alpine AS runtime
COPY --from=nginx default.conf /etc/nginx/conf.d/default.conf
COPY --from=nginx security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /build/dist/frontend/browser /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["wget", "--quiet", "--spider", "http://127.0.0.1:8080/"]
