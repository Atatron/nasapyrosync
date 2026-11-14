# PyroSync read-only demo for a Hugging Face Docker Space (or any container host: Cloud Run, a VPS, ...).
# Unlike Vercel functions, a container has no 250 MB cap, so the full archive with all five satellites fits.
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYROSYNC_READONLY=1 PYROSYNC_DATA_DIR=/tmp/pyrosync PYROSYNC_SEED_DB=/app/data/pyrosync-full.duckdb \
    PYTHONPATH=/app/backend
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "uvicorn==0.54.0"
COPY backend/pyrosync backend/pyrosync
COPY frontend/dist frontend/dist
COPY data/pyrosync-full.duckdb data/pyrosync-full.duckdb
# Hugging Face runs the container as user 1000 and expects port 7860; other hosts can set PORT.
RUN useradd -m -u 1000 user && mkdir -p /tmp/pyrosync && chown -R user /tmp/pyrosync
USER user
EXPOSE 7860
CMD ["sh", "-c", "python -m pyrosync.cli serve --host 0.0.0.0 --port ${PORT:-7860}"]
