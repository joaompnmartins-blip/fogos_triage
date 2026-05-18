# =====================================================================
# Frontend — React + Vite → Nginx static
# =====================================================================
FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci --prefer-offline

COPY . .

# VITE_API_URL é injectada pelo Railway como build arg e runtime env.
# O Vite embute-a no bundle no momento do build — não é lida em runtime.
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build

# =====================================================================
FROM nginx:1.27-alpine AS serve

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
