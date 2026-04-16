FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
ENV CHROME_FLAGS="--no-sandbox --disable-gpu --disable-dev-shm-usage --remote-debugging-port=9222 --remote-debugging-address=0.0.0.0 --window-size=1920,1080"

# Install dependencies + Chrome in one layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg xvfb x11vnc fluxbox supervisor \
    ca-certificates fonts-liberation \
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 \
    libasound2 libpango-1.0-0 libpangocairo-1.0-0 \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub \
       | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Set up VNC password
RUN mkdir -p /root/.vnc && \
    x11vnc -storepasswd spec2sphere /root/.vnc/passwd

# Supervisor config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose ports: 5900=VNC, 9222=CDP
EXPOSE 5900 9222

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
