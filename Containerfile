FROM python:3.13-slim

WORKDIR /app
COPY server /app/server

ENV AI_LOG_HOST=0.0.0.0
ENV AI_LOG_PORT=8888
ENV AI_LOG_DATA_DIR=/data

EXPOSE 8888

CMD ["python", "-m", "server.main"]
