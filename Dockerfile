# Базовый образ
FROM python:3.13-slim

# Установка зависимостей системы
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Установка Poetry через pip
RUN pip install --no-cache-dir poetry

# Настройки Poetry
ENV POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

# Создание рабочей директории
WORKDIR /app

# Копирование файлов Poetry
COPY pyproject.toml poetry.lock* /app/

# Установка зависимостей проекта
RUN poetry install --no-root

# Копирование исходного кода
COPY . /app

# Открытие порта
EXPOSE 8000

# Запуск FastAPI через Uvicorn (путь может отличаться)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
