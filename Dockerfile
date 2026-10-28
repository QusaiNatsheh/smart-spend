FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN DJANGO_DEBUG=False DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput \
    && useradd --create-home app && mkdir -p /data && chown app /data
USER app

ENV DJANGO_DB_PATH=/data/db.sqlite3
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn smart_spend.wsgi --bind 0.0.0.0:8000 --workers 2 --timeout 240"]
