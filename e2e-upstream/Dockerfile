# ffmpeg builder stage is added in Task 4; this is the runtime-only shape.
FROM node:24-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df AS runtime
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json ./
COPY src ./src
RUN npx tsc
EXPOSE 8080
CMD ["node", "dist/index.js"]
