from django.apps import AppConfig


class CollaborationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'collaboration'

    def ready(self):
        from . import signals  # noqa: F401  (registers the Document audit-log receivers)
