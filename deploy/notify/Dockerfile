FROM python:3.11-alpine

WORKDIR /app
COPY notify.py /app/notify.py

RUN adduser -D -u 1000 notify
USER 1000:1000

EXPOSE 8080
CMD ["python", "/app/notify.py"]
