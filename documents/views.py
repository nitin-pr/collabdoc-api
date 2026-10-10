import uuid

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from collaboration.models import Tag
from common.utils import parse_csv_param, parse_uuid_param

from .models import Document, DocumentVersion
from .serializers import (
    AddTagsSerializer,
    DocumentSerializer,
    DocumentUpdateSerializer,
    DocumentVersionSerializer,
)

TRUTHY = ('1', 'true', 'yes', 'on')


class SimulatedFailure(Exception):
    """Raised on purpose, after the writes, to demonstrate that atomic() rolls everything back."""


def wants_simulated_failure(request):
    """
    `"simulate_failure": true` in the body makes the request fail after the document and its
    version have been written. Only honoured when DEBUG is on, so it can never fire in production.
    """
    if str(request.data.get('simulate_failure', '')).lower() not in TRUTHY:
        return False
    if not settings.DEBUG:
        raise ValidationError({'simulate_failure': 'Only available when DJANGO_DEBUG=True.'})
    return True


def save_version(document, saved_by):
    """
    Snapshot the document's current content as its next version.

    Must be called inside transaction.atomic(), straight after the document row is saved.
    The number is per document (count + 1), not a global counter.
    """
    return DocumentVersion.objects.create(
        document=document,
        content=document.content,
        version_number=document.versions.count() + 1,
        saved_by=saved_by,
    )


class DocumentViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    POST /api/documents/                  create a document + version 1 (atomic)
    PUT  /api/documents/{id}/             update content, saving a new version (atomic)
    GET  /api/documents/                  list, filter by workspace / status / tag, search
    GET  /api/documents/{id}/versions/    all versions in order
    GET  /api/documents/{id}/stats/       version, comment and contributor counts
    POST /api/documents/{id}/tags/        add one or more tags
    """

    serializer_class = DocumentSerializer

    def detailed_queryset(self):
        """Documents as they appear in responses: related rows joined, tags prefetched, versions counted."""
        return (
            Document.objects.select_related('workspace', 'created_by')
            .prefetch_related('tags')
            .annotate(version_count=Count('versions', distinct=True))
        )

    def get_queryset(self):
        if self.action in ('retrieve', 'list'):
            return self.detailed_queryset()
        # update / versions / stats / tags only need to find the row, so skip the joins and the prefetch.
        return Document.objects.all()

    # ---- create / update (transactions) ------------------------------------------------------

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fail_on_purpose = wants_simulated_failure(request)

        try:
            with transaction.atomic():
                document = serializer.save()  # post_save signal writes the AuditLog in this same block
                save_version(document, saved_by=document.created_by)
                if fail_on_purpose:
                    raise SimulatedFailure
        except SimulatedFailure:
            return self._rolled_back_response()
        except IntegrityError:
            return Response(
                {'detail': 'Could not save the document because of a data conflict.'},
                status=status.HTTP_409_CONFLICT,
            )

        document = self.detailed_queryset().get(pk=document.pk)
        return Response(self.get_serializer(document).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        document = self.get_object()  # 404 for an unknown or malformed ID
        serializer = DocumentUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        fail_on_purpose = wants_simulated_failure(request)

        try:
            with transaction.atomic():
                # Lock the row so two simultaneous updates cannot be handed the same version number.
                document = Document.objects.select_for_update().get(pk=document.pk)
                document.content = data['content']
                for field in ('title', 'status'):
                    if field in data:
                        setattr(document, field, data[field])
                document.save()  # post_save signal writes the AuditLog in this same block
                save_version(document, saved_by=data.get('saved_by'))
                if fail_on_purpose:
                    raise SimulatedFailure
        except Document.DoesNotExist:
            return Response({'detail': 'Document not found.'}, status=status.HTTP_404_NOT_FOUND)
        except SimulatedFailure:
            return self._rolled_back_response()
        except IntegrityError:
            return Response(
                {'detail': 'Could not save the document because of a data conflict.'},
                status=status.HTTP_409_CONFLICT,
            )

        document = self.detailed_queryset().get(pk=document.pk)
        return Response(self.get_serializer(document).data)

    @staticmethod
    def _rolled_back_response():
        return Response(
            {'detail': 'Simulated failure: the transaction was rolled back and nothing was saved.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ---- list with filters --------------------------------------------------------------------

    def get_filtered_queryset(self):
        params = self.request.query_params
        queryset = self.detailed_queryset()

        workspace = params.get('workspace')
        if workspace:
            queryset = queryset.filter(workspace_id=parse_uuid_param('workspace', workspace))

        created_by = params.get('created_by')
        if created_by:
            queryset = queryset.filter(created_by_id=parse_uuid_param('created_by', created_by))

        statuses = params.get('status')
        if statuses:
            wanted = parse_csv_param(statuses)
            invalid = [value for value in wanted if value not in Document.Status.values]
            if invalid:
                raise ValidationError({'status': f'Invalid status: {", ".join(invalid)}. '
                                                 f'Choose from {", ".join(Document.Status.values)}.'})
            queryset = queryset.filter(status__in=wanted)

        tags = params.get('tag')
        if tags:
            # A document matches if it carries ANY of the listed tags (OR), case-insensitively.
            tag_filter = Q()
            for name in parse_csv_param(tags):
                tag_filter |= Q(tags__name__iexact=name)
            queryset = queryset.filter(tag_filter).distinct()

        search = params.get('search')
        if search:
            queryset = queryset.filter(Q(title__icontains=search) | Q(content__icontains=search))

        return queryset.order_by('-updated_at')

    def list(self, request, *args, **kwargs):
        queryset = self.get_filtered_queryset()
        return Response(self.get_serializer(queryset, many=True).data)

    # ---- extra endpoints ----------------------------------------------------------------------

    @action(detail=True, methods=['get'], url_path='versions')
    def versions(self, request, pk=None):
        document = self.get_object()
        versions = document.versions.select_related('saved_by').order_by('version_number')
        return Response(DocumentVersionSerializer(versions, many=True).data)

    @action(detail=True, methods=['get'], url_path='stats')
    def stats(self, request, pk=None):
        document = self.get_object()
        # Contributors are the distinct users who saved at least one version of this document.
        counts = Document.objects.filter(pk=document.pk).aggregate(
            version_count=Count('versions', distinct=True),
            comment_count=Count('comments', distinct=True),
            contributor_count=Count('versions__saved_by', distinct=True),
            tag_count=Count('tags', distinct=True),
            latest_version=Max('versions__version_number'),
        )
        return Response({'document': document.id, 'title': document.title, **counts})

    @action(detail=True, methods=['post'], url_path='tags')
    def tags(self, request, pk=None):
        document = self.get_object()
        serializer = AddTagsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ids, names, requested = [], [], []
        for item in serializer.validated_data['tags']:
            item = item.strip()
            try:
                key = str(uuid.UUID(item))
                ids.append(key)
            except ValueError:
                key = item.lower()
                names.append(key)
            requested.append(key)

        found = list(Tag.objects.filter(Q(id__in=ids) | Q(name__in=names)))
        matched = {str(tag.id) for tag in found} | {tag.name for tag in found}
        missing = [key for key in requested if key not in matched]
        if missing:
            return Response(
                {'detail': 'Tag not found. Create it first with POST /api/tags/.', 'missing': missing},
                status=status.HTTP_404_NOT_FOUND,
            )

        document.tags.add(*found)  # adding an already-attached tag is a harmless no-op
        current = document.tags.values_list('name', flat=True).order_by('name')
        return Response({'document': document.id, 'tags': list(current)})
