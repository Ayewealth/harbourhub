#!/usr/bin/env bash
set -o errexit  # exit on error

echo "🚀 Starting build process..."

# Install dependencies
pip install -r requirements.txt

# Collect static files
python manage.py collectstatic --noinput

# Run database migrations
python manage.py migrate --noinput

# Create sample data (runs only if DB is empty)
python manage.py create_sample_data --users 30 --listings 80 --inquiries 150

echo "✅ Build complete!"
