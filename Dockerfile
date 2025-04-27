# Use Python 3.11 slim version as the base image
FROM python:3.11-slim-bullseye

# Set environment variables for Python
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set environment variables for Django and Celery (can be overridden by docker-compose)
ENV DJANGO_SETTINGS_MODULE=meetinginsight.settings # Adjust if your settings module path is different
ENV CELERY_BROKER_URL=redis://redis:6379/0
ENV CELERY_RESULT_BACKEND=redis://redis:6379/0
# Remember to set DATABASE_URL, SECRET_KEY, DEBUG, OPENROUTER_API_KEY etc. via env_file or environment in docker-compose

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
# - build-essential: Needed if any Python packages compile C extensions during pip install
# - libpq5: Runtime library for connecting to PostgreSQL using psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq5 \
    # Add any other system dependencies needed by your Python packages
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip

# Copy only the requirements file first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

 RUN apt-get remove -y --purge build-essential \
     && apt-get autoremove -y --purge \
     && rm -rf /var/lib/apt/lists/*

# Copy the rest of the application code into the container
COPY . .

# Create directories for static and media files if they don't exist
# These will typically be mounted via volumes in docker-compose for development/persistence
RUN mkdir -p /app/staticfiles /app/media

# Create a non-root user and group to run the application
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Run collectstatic - Do this *before* changing ownership if staticfiles dir needs root write access initially
# Ensure your settings are configured correctly for static files collection
RUN python manage.py collectstatic --noinput

# Change ownership of the application directory and created volumes to the non-root user
# This includes the code, staticfiles, and media directories
RUN chown -R appuser:appgroup /app

# Switch to the non-root user
USER appuser

# Expose the port the application will run on
EXPOSE 8000

# Define the default command to run the application using Gunicorn
# Make sure gunicorn is in your requirements.txt
CMD ["gunicorn", "meetinginsight.wsgi:application", "--bind", "0.0.0.0:8000"]