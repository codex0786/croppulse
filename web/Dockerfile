FROM node:20-alpine AS build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine
WORKDIR /web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build /web/.next ./.next
COPY --from=build /web/public ./public
COPY --from=build /web/next.config.js ./next.config.js
COPY --from=build /web/package.json /web/package-lock.json ./
RUN npm ci --omit=dev && adduser -D -u 10001 web
USER web
EXPOSE 3000
CMD ["npx", "next", "start", "-p", "3000"]
