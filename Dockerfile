FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg portaudio19-dev gcc \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY be ./be
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser
WORKDIR /app/be
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
