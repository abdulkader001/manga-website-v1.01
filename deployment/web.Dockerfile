# Pinned by digest (roadmap item 21). Node must stay >= 22.12 for Vite 7.
# Dependabot proposes newer digests; see deployment/updating.md.
ARG FRONTEND_NODE_IMAGE=docker.io/library/node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402
ARG FRONTEND_NGINX_IMAGE=docker.io/library/nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10

FROM ${FRONTEND_NODE_IMAGE} AS build

ARG FRONTEND_NODE_IMAGE
ARG CI=false
ENV CI=${CI}
# F-71: never ship source maps -- they carry the complete original source of
# every file (admin routes and role gates included). vite.config.ts reads this.
ENV GENERATE_SOURCEMAP=false
LABEL build.frontend_node_image=${FRONTEND_NODE_IMAGE}

WORKDIR /app

COPY package.json package-lock.json ./
# `npm ci` installs exactly what package-lock.json pins.
RUN npm ci --no-audit --no-fund

COPY index.html vite.config.ts postcss.config.js tailwind.config.js tsconfig.json ./
COPY public ./public
COPY src ./src
RUN npm run build \
 && find dist -name '*.map' -delete \
 && if find dist -name '*.map' | grep -q .; then \
      echo 'ERROR: source maps present in build output'; exit 1; \
    fi

FROM ${FRONTEND_NGINX_IMAGE} AS runtime

ARG FRONTEND_NGINX_IMAGE
LABEL build.frontend_nginx_image=${FRONTEND_NGINX_IMAGE}

WORKDIR /usr/share/nginx/html
RUN rm -rf ./*

# Copy the site configuration that serves the React build.
COPY deployment/nginx/site.conf /etc/nginx/conf.d/default.conf

# Override the default nginx.conf so nginx can write its PID file while
# running as an unprivileged user inside the container.
COPY deployment/nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist ./

# Runtime config (/config.json): rendered from the API_BASE env var at
# container start so the frontend can be repointed without a rebuild.
COPY deployment/nginx/config.json.template /etc/nginx/runtime-config/config.json.template
COPY deployment/nginx/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV API_BASE=/api/v1

RUN chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx /var/run /var/log/nginx

EXPOSE 8080

USER nginx

ENTRYPOINT ["/entrypoint.sh"]

# The entrypoint renders /config.json and then `exec "$@"`. Without a default
# CMD that "$@" is empty, so `docker run` of this image on its own execs
# nothing and the container exits immediately — it only ever worked because
# docker-compose supplies the command. The PID file goes to /tmp because the
# container runs as the unprivileged `nginx` user.
CMD ["nginx", "-g", "pid /tmp/nginx.pid; daemon off;"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD sh -c 'wget --quiet --tries=1 http://127.0.0.1:8080/ -O - >/dev/null'
