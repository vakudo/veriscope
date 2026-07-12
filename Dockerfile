FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --gid 10001 veriscope \
    && useradd --uid 10001 --gid veriscope --create-home --shell /usr/sbin/nologin veriscope

WORKDIR /srv/veriscope

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=veriscope:veriscope app ./app

USER veriscope

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=4)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
