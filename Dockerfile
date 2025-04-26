# Stage 1: Build environment with dependencies
FROM python:3.11-slim-bullseye AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

# Install system dependencies (libpq-dev might not be strictly needed with psycopg[binary])
# Keeping build-essential just in case other packages need it.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    # libpq-dev # Removed, psycopg[binary] should handle it
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /wheels -r requirements.txt


# Stage 2: Final runtime image
FROM python:3.11-slim-bullseye AS runtime

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV DJANGO_SETTINGS_MODULE=meetinginsight.settings # Adjust if your settings module path is different
ENV CELERY_BROKER_URL=redis://redis:6379/0
ENV CELERY_RESULT_BACKEND=redis://redis:6379/0
# DATABASE_URL, SECRET_KEY, DEBUG, OPENROUTER_API_KEY etc. should be set via env_file

# Set work directory
WORKDIR /app

# Install system dependencies required at runtime (postgres client libs for psycopg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user and group
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Copy installed dependencies from builder stage
COPY --from=builder /wheels /wheels
COPY --from=builder /app/requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt && rm -rf /wheels

# Copy application code
COPY . .

# Set permissions for static/media directories if they exist in the code
RUN mkdir -p /app/staticfiles /app/media && \
    chown -R appuser:appgroup /app/staticfiles /app/media

# Collect static files
RUN python manage.py collectstatic --noinput
RUN chown -R appuser:appgroup /app/staticfiles

# Change ownership of the entire app directory to the non-root user
RUN chown -R appuser:appgroup /app

# Switch to the non-root user
USER appuser

# Expose the port the app runs on
EXPOSE 8000

# Default command (Use Gunicorn)
CMD ["gunicorn", "meetinginsight.wsgi:application", "--bind", "0.0.0.0:8000"]