# Shipping document verification: one container serves the API and the web page.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# constraints.txt pins the exact versions the results were measured with
COPY requirements.txt constraints.txt ./
RUN pip install -r requirements.txt -c constraints.txt

COPY . .

# Reviewer decisions and the AI cache are written next to the app, so it needs to own its folder
RUN useradd --create-home app && mkdir -p /app/state && chown -R app:app /app
USER app

# Cloud Run and Render set PORT themselves; 8080 is the fallback
ENV PORT=8080
EXPOSE 8080

# One worker on purpose: results are held in memory, so a second worker would hold its own copy
CMD ["sh", "-c", "exec gunicorn app:app --workers 1 --threads 4 --timeout 180 --bind 0.0.0.0:${PORT}"]
