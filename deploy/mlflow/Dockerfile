# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir \
    mlflow==3.18.0 \
    "psycopg[binary]>=3.2" \
    boto3==1.43.117

EXPOSE 5000
