FROM node:22-slim

# Instalar Chromium + librerías necesarias para headless
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    fonts-liberation \
    libnss3 \
    libxss1 \
    libasound2 \
    libgbm1 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Path estándar donde apt deja Chromium en Debian
ENV CHROME_PATH=/usr/bin/chromium

WORKDIR /app

# Copiar solo package files primero para cachear npm install
COPY package*.json ./
RUN npm ci --omit=dev

# Copiar el resto del código
COPY . .

EXPOSE 8080

CMD ["node", "server.js"]