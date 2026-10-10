"""
Root URL configuration.

A single DefaultRouter serves every endpoint under /api/. Each app declares its
own routes in `<app>/routes.py` as a list of (prefix, viewset, basename) tuples,
so a new endpoint never needs a change to this file.

Every URL works with or without its trailing slash (`/api/users` and `/api/users/`).
Django cannot redirect a POST or PUT to the slash version without losing the body,
so without this a request typed without the slash would fail instead of being served.
"""

from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from collaboration.routes import ROUTES as COLLABORATION_ROUTES
from documents.routes import ROUTES as DOCUMENT_ROUTES
from users.routes import ROUTES as USER_ROUTES
from workspaces.routes import ROUTES as WORKSPACE_ROUTES

router = DefaultRouter()
# The constructor only accepts True/False; setting the regex piece directly makes the slash optional.
router.trailing_slash = '/?'

for prefix, viewset, basename in (
    *USER_ROUTES,
    *WORKSPACE_ROUTES,
    *DOCUMENT_ROUTES,
    *COLLABORATION_ROUTES,
):
    router.register(prefix, viewset, basename=basename)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),
]
