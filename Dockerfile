FROM python:3.13-slim as base

# Установка зависимостей системы
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpq-dev \
    pkg-config \
    postgresql-client \
  && rm -rf /var/lib/apt/lists/*

# Установка grpc_health_probe для health checks gRPC

# Установка Poetry через pip
RUN pip install --no-cache-dir poetry

# Настройки Poetry
ENV POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

# Создание рабочей директории
WORKDIR /app

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/entrypoint.sh \
    && sed -i 's/\r$//' /usr/local/bin/entrypoint.sh

# Копирование файлов Poetry
COPY pyproject.toml poetry.lock* /app/

# Установка зависимостей проекта
RUN poetry install --no-root

# Копирование исходного кода
COPY . /app


RUN adduser --disabled-password --gecos '' appuser && \
    chown -R appuser:appuser /app
USER appuser


ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

## FastAPI target
#FROM base as fastapi
#EXPOSE 8000
#HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
#  CMD curl -f http://localhost:8000/health || exit 1
#CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
#
## gRPC target
#FROM base as grpc
#EXPOSE 50051
#HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
#  CMD grpc_health_probe -addr=localhost:50051 || exit 1
#CMD ["python", "rpc_server/serve_rpc.py"]