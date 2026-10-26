FROM denoland/deno:bin-2.5.6 AS deno-runtime

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app

# Recent YouTube player responses require a supported JavaScript runtime for
# yt-dlp's EJS challenge solver. The Python package alone is not sufficient.
COPY --from=deno-runtime /deno /usr/local/bin/deno

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg portaudio19-dev gcc \
    && deno --version \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY be ./be
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser
WORKDIR /app/be
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
