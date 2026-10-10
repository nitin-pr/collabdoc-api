"""Routes for the collaboration app, registered on the project-wide DefaultRouter in config/urls.py."""

from .views import AuditLogViewSet, CommentViewSet, TagViewSet

ROUTES = [
    ('comments', CommentViewSet, 'comment'),
    ('tags', TagViewSet, 'tag'),
    ('audit-logs', AuditLogViewSet, 'audit-log'),
]
