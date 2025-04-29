#!/bin/sh

# Exit immediately if a command exits with a non-zero status.
set -e

# Optional: Add a wait loop here if you need to wait for a database container.
# Example for PostgreSQL (requires psql client installed in image via apt-get install postgresql-client):
# while ! psql $DATABASE_URL -c '\q'; do
#   >&2 echo "Postgres is unavailable - sleeping"
#   sleep 1
# done
# >&2 echo "Postgres is up - executing command"
# Note: Since you're likely using an external DB (Neon), a simple wait loop
# might not be sufficient, but migrations should retry or fail if the DB isn't ready.

echo "Applying database migrations..."
python manage.py migrate --noinput
echo "Database migrations complete."

# Execute the command provided as arguments to this script
# (This will be the CMD from the Dockerfile or command from docker-compose)
exec "$@"