from django.apps import AppConfig


class CoreappConfig(AppConfig):
    name = 'coreapp'

    def ready(self):
        from . import signals  # noqa: F401
