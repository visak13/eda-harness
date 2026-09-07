# --- web build stage: compile the Vite SPA with Node (LL §13 engines floor: node >=24) ---
FROM node:24-alpine AS web
WORKDIR /app
# Install deps against the committed lockfile first (cache-friendly), then build.
COPY web/package.json web/package-lock.json ./web/
RUN npm --prefix web ci
COPY web ./web
# vite.config.ts outDir is ../src/edp8/webapp/dist → writes to /app/src/edp8/webapp/dist
RUN npm --prefix web run build

# --- python stage: install the package and ship the built SPA inside it ---
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY guides ./guides
# The gitignored dist is force-included into the wheel; here we copy the built bundle in
# before install so the SPA is served (mount_spa /app) and packaged.
COPY --from=web /app/src/edp8/webapp/dist ./src/edp8/webapp/dist
RUN pip install --no-cache-dir .
EXPOSE 9400
CMD ["edp8-board"]
