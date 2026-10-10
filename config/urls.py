"""
Root URL configuration.

A single DefaultRouter serves every endpoint under /api/. Each app declares its
own routes in `<app>/routes.py` as a list of (prefix, viewset, basename) tuples,
so teammates never need to edit this file to add an endpoint.
"""

from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from collaboration.routes import ROUTES as COLLABORATION_ROUTES
from documents.routes import ROUTES as DOCUMENT_ROUTES
from users.routes import ROUTES as USER_ROUTES
from workspaces.routes import ROUTES as WORKSPACE_ROUTES

router = DefaultRouter()

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
