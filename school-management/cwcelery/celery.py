# celery -A cwcelery worker -l info

from __future__ import absolute_import, unicode_literals

from celery import Celery

app = Celery("cwcelery")

# Unclear whether or not this is necessary
# os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.jordan_local")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django app configs. So all apps' tasks.py will get discovered
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    print("Request: {0!r}".format(self.request))
