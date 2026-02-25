FROM python:3.12-slim

# Chrome + 필수 시스템 라이브러리 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg2 unzip \
    fonts-liberation libnss3 libxss1 libasound2 libatk-bridge2.0-0 \
    libgtk-3-0 libdrm2 libgbm1 libx11-xcb1 libxcomposite1 \
    libxdamage1 libxrandr2 xdg-utils \
    && wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y /tmp/chrome.deb \
    && rm /tmp/chrome.deb \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ARG CACHE_BUST=2
COPY . .

ENV CHROME_BIN=/usr/bin/google-chrome
ENV PYTHONUNBUFFERED=1

CMD ["python", "rank.py"]
