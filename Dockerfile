# ビルド用ステージ
FROM python:3.12-alpine AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apk add --no-cache build-base libffi-dev

WORKDIR /app

COPY requirements.txt ./
RUN pip install --prefix=/install -r requirements.txt

FROM python:3.12-alpine AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN addgroup -g 1000 app \
    && adduser -D -u 1000 -G app app \
    && mkdir -p /app/data \
    && chown -R app:app /app

COPY --from=builder /install /usr/local
COPY --chown=app:app src ./src

RUN python -m compileall -q -f src \
    && chown -R app:app src

USER app

CMD ["python", "-m", "src.main"]
