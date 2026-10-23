FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PORT=8080

RUN python manage.py collectstatic --noinput

CMD python manage.py migrate --noinput && \
    gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} --workers 2 --threads 4
