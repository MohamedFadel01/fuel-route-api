FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_DEBUG=false \
    DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin app

COPY requirements/base.txt requirements/base.txt
RUN pip install --no-cache-dir -r requirements/base.txt

COPY --chown=app:app . .
RUN chmod +x scripts/serve.sh && chown app:app /app

USER app
EXPOSE 8000
CMD ["scripts/serve.sh"]
