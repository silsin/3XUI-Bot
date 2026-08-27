# syntax=docker/dockerfile:1
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# نصب وابستگی‌ها به‌صورت لایه جدا برای کش بهتر
COPY requirements.txt .
RUN pip install -r requirements.txt

# کد برنامه
COPY app ./app
COPY bot.py ./

# کاربر غیر-root و مالکیت پوشه دیتا (SQLite)
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

VOLUME ["/app/data"]

CMD ["python", "bot.py"]
