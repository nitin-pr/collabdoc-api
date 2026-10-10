"""Routes for the workspaces app, registered on the project-wide DefaultRouter in config/urls.py."""

from .views import WorkspaceViewSet

ROUTES = [('workspaces', WorkspaceViewSet, 'workspace')]
