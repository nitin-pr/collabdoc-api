"""Routes for the documents app, registered on the project-wide DefaultRouter in config/urls.py."""

from .views import DocumentViewSet

ROUTES = [('documents', DocumentViewSet, 'document')]
