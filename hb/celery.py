# hb/celery.py
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hb.settings')

app = Celery('hb')

# read broker/result from env (already in settings via decouple)
app.config_from_object('django.conf:settings', namespace='CELERY')

# autodiscover tasks across installed apps
app.autodiscover_tasks()

# sensible defaults
app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')