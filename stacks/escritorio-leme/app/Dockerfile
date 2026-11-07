FROM python:3.13-alpine
RUN apk add --no-cache git
WORKDIR /app
COPY server.py ./
COPY static ./static
ENV PYTHONUNBUFFERED=1 HOME=/tmp GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0=*
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:8000/healthz || exit 1
CMD ["python", "-I", "server.py"]
