# ---------- STAGE 1: build the React app ----------
FROM node:20-alpine AS build
WORKDIR /app

COPY package*.json ./
# npm ci needs package-lock.json (created the first time you run `npm install`).
# Fall back to npm install so the very first build also works.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY . .
RUN npm run build

# ---------- STAGE 2: serve the built files ----------
FROM nginx:alpine

# This is a Vite project, so the build output is /app/dist
COPY --from=build /app/dist /usr/share/nginx/html

# Our own config: SPA refresh fix + /api proxy to the backend
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
