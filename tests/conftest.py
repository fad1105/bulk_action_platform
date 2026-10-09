import pytest

from config.celery import app as celery_app


@pytest.fixture(autouse=True)
def configure_celery_for_tests(settings):
    """Ensure tests run Celery tasks in eager mode and never pollute the Redis queue."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    celery_app.conf.task_always_eager = True
    yield
    celery_app.conf.task_always_eager = False
