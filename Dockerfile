# Use Python 3.11 slim version as the base image
FROM python:3.11-slim-bullseye

# Set environment variables for Python
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set environment variables for Django and Celery (can be overridden by docker-compose)
ENV DJANGO_SETTINGS_MODULE=meetinginsight.settings
ENV CELERY_BROKER_URL=redis://redis:6379/0
ENV CELERY_RESULT_BACKEND=redis://redis:6379/0
# Remember to set DATABASE_URL, SECRET_KEY, DEBUG, OPENROUTER_API_KEY etc. via env_file or environment in docker-compose

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
# - build-essential: Needed for packages compiling C extensions during pip install
# - libpq5: Runtime library for connecting to PostgreSQL using psycopg
# - postgresql-client: Optional, only needed if using psql in entrypoint wait loop
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq5 \
    # postgresql-client \ # Uncomment if using psql wait loop in entrypoint.sh
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip

# Copy only the requirements file first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Clean up build dependencies (reduces image size)
RUN apt-get remove -y --purge build-essential \
     && apt-get autoremove -y --purge \
     && rm -rf /var/lib/apt/lists/*

# Copy the rest of the application code into the container
COPY . .

# Copy the entrypoint script and make it executable
COPY ./entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Create directories for static and media files
RUN mkdir -p /app/staticfiles /app/media

# Create a non-root user and group to run the application
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Run collectstatic - uses settings to find static files and copy to STATIC_ROOT
# Ensure STATIC_ROOT is set correctly in settings.py (e.g., STATIC_ROOT = BASE_DIR / "staticfiles")
RUN python manage.py collectstatic --noinput

# Change ownership of the application directory and created volumes to the non-root user
# This includes the code, staticfiles, and media directories
RUN chown -R appuser:appgroup /app

# Switch to the non-root user
USER appuser

# Expose the port the application will run on
EXPOSE 8000

# Set the entrypoint script to run on container start
ENTRYPOINT ["/app/entrypoint.sh"]

# Define the default command (arguments passed to the entrypoint script via "$@")
CMD ["gunicorn", "meetinginsight.wsgi:application", "--bind", "0.0.0.0:8000"]