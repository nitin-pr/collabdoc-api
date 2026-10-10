"""Routes for the users app, registered on the project-wide DefaultRouter in config/urls.py."""

from .views import UserViewSet

ROUTES = [('users', UserViewSet, 'user')]
