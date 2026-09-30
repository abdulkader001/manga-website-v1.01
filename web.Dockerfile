ARG FRONTEND_NODE_IMAGE=docker.io/library/node:22-alpine
ARG FRONTEND_NGINX_IMAGE=docker.io/library/nginx:1.27-alpine

FROM ${FRONTEND_NODE_IMAGE} AS build

ARG FRONTEND_NODE_IMAGE
ARG REACT_APP_API_BASE=/api/v1
ARG CI=false

ENV REACT_APP_API_BASE=${REACT_APP_API_BASE}
ENV CI=${CI}
# F-71: CRA emits .map files with sourcesContent:true, i.e. the complete
# original text of every source file, and they were being served with a 200 in
# production -- the whole frontend, admin routes and role gates included, free
# to download. If you want maps for error tracking, generate them in a
# separate build and upload them privately to Sentry; never ship them.
ENV GENERATE_SOURCEMAP=false
# Load-bearing for the CSP in nginx.conf: by default CRA inlines the webpack
# runtime as a <script> block inside index.html, which `script-src 'self'`
# (no 'unsafe-inline') blocks -- the page would render blank. Emitting it as a
# separate file keeps the strict policy and the app working.
ENV INLINE_RUNTIME_CHUNK=false
LABEL build.frontend_node_image=${FRONTEND_NODE_IMAGE}

WORKDIR /app

COPY frontend/package*.json ./
# `npm ci` installs exactly what package-lock.json pins; `npm install` is free
# to resolve newer transitive versions, so two builds of the same commit could
# ship different dependency trees.
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build \
 && find build -name '*.map' -delete \
 && if find build -name '*.map' | grep -q .; then \
      echo 'ERROR: source maps present in build output'; exit 1; \
    fi

FROM ${FRONTEND_NGINX_IMAGE} AS runtime

ARG FRONTEND_NGINX_IMAGE
LABEL build.frontend_nginx_image=${FRONTEND_NGINX_IMAGE}

WORKDIR /usr/share/nginx/html
RUN rm -rf ./*

# Copy the site configuration that serves the React build.
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Override the default nginx.conf so nginx can write its PID file while
# running as an unprivileged user inside the container.
COPY deploy/nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/build ./

# Runtime config (/config.json): rendered from the API_BASE env var at
# container start so the frontend can be repointed without a rebuild.
COPY deploy/nginx/config.json.template /etc/nginx/runtime-config/config.json.template
COPY deploy/nginx/entrypoint.sh /entrypoint.sh
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
