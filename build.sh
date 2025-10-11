#!/usr/bin/env bash
# Exit on error
set -o errexit

# Install dependencies
pip install -r requirements.txt

# Run migrations & collectstatic
python manage.py migrate --noinput
python manage.py collectstatic --noinput
