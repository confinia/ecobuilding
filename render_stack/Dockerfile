# Puppeteer base image bundles Chrome + all system libs (WebGL via SwiftShader).
# PUPPETEER_SKIP_DOWNLOAD/EXECUTABLE_PATH are preset, so `npm install puppeteer`
# reuses the bundled browser instead of re-downloading it.
FROM ghcr.io/puppeteer/puppeteer:22.15.0
USER root
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev && chown -R pptruser:pptruser /app
COPY server.js render.html ./
USER pptruser
EXPOSE 8040
CMD ["node", "server.js"]
