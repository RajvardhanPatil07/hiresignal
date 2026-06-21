FROM node:22-alpine AS build

WORKDIR /app

ARG VITE_HIRESIGNAL_API_BASE_URL=http://localhost:8000
ARG VITE_HIRESIGNAL_API_KEY=dev-api-key-change-in-production

ENV VITE_HIRESIGNAL_API_BASE_URL=$VITE_HIRESIGNAL_API_BASE_URL
ENV VITE_HIRESIGNAL_API_KEY=$VITE_HIRESIGNAL_API_KEY

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
