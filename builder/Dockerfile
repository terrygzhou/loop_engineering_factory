FROM python:3.12-slim

# Heavy deps: Playwright + Docker CLI
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg \
    libglib2.0-0 libnss3 libnspr4 libx11-6 libx11-xcb1 libxcb1 \
    libxcomposite1 libxcursor1 libxdamage1 libxext6 libxfixes3 \
    libxi6 libxrandr2 libxrender1 libxss1 libxtst6 \
    libxkbcommon0 libpango-1.0-0 libcairo2 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libdrm2 libgbm1 libasound2 \
    fonts-liberation \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | \
       gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
       https://download.docker.com/linux/debian bookworm stable" \
       > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y docker-ce-cli docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt playwright
RUN python3 -m playwright install chromium

WORKDIR /app
COPY builder/ ./builder/
COPY config/ ./config/
COPY service/ ./service/
COPY tools/ ./tools/
COPY log/ ./log/
COPY skills/ ./skills/
COPY graph/nodes/build_helpers.py ./graph/nodes/build_helpers.py

EXPOSE 8200
CMD ["uvicorn", "builder.api:app", "--host", "0.0.0.0", "--port", "8200"]