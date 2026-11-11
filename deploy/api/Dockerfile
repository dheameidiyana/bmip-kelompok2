FROM python:3.11-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    API_PORT=8000

RUN addgroup -g 10001 -S api \
    && adduser -u 10001 -S -G api -h /app api

WORKDIR /app
COPY --chown=10001:10001 server.py /app/server.py

USER 10001:10001
EXPOSE 8000

CMD ["python", "server.py"]
