# =====================================================================
# Frontend — React + Vite → Nginx static
# =====================================================================
FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci --prefer-offline

COPY . .

# Estas variáveis são injectadas pelo Railway como build args.
# O Vite embute-as no bundle no momento do build — não são lidas em runtime.
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL
ARG VITE_REGION_BBOX
ENV VITE_REGION_BBOX=$VITE_REGION_BBOX
ARG VITE_REGION_CENTER
ENV VITE_REGION_CENTER=$VITE_REGION_CENTER
ARG VITE_REGION_ZOOM
ENV VITE_REGION_ZOOM=$VITE_REGION_ZOOM
ARG VITE_REGION_LABEL
ENV VITE_REGION_LABEL=$VITE_REGION_LABEL

RUN npm run build

# =====================================================================
FROM nginx:1.27-alpine AS serve

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
