FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TGKR_BASE_DIR=/app \
    TGKR_DATA_DIR=/app/data \
    TGKR_DB_PATH=/app/data/state.db \
    TGKR_SESSION_PATH=/app/data/account \
    TGKR_HOST=127.0.0.1 \
    TGKR_PORT=8100

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data \
    && useradd --system --create-home --uid 10001 tgkr \
    && chown -R tgkr:tgkr /app

USER tgkr

EXPOSE 8100

CMD ["python", "main.py"]
