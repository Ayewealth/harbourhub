web: gunicorn hb.wsgi:application --timeout 120 --log-file -
worker: celery -A hb worker --loglevel=info
beat: celery -A hb beat --loglevel=info
