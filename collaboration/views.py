from collections import defaultdict

from django.db import IntegrityError, transaction
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from common.utils import parse_csv_param, parse_datetime_param, parse_uuid_param
from documents.models import Document

from .models import AuditLog, Comment, Tag
from .serializers import AuditLogSerializer, CommentSerializer, TagSerializer


class CommentViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    POST /api/comments/                  add a top-level comment (parent omitted) or a reply (parent = comment id)
    GET  /api/comments/?document={id}    every comment on a document, replies nested under their parent
    """

    serializer_class = CommentSerializer

    def get_queryset(self):
        return Comment.objects.select_related('author')

    def list(self, request, *args, **kwargs):
        raw_document = request.query_params.get('document')
        if not raw_document:
            raise ValidationError({'document': 'This query parameter is required, e.g. ?document=<document id>.'})
        document_id = parse_uuid_param('document', raw_document)
        if not Document.objects.filter(pk=document_id).exists():
            return Response({'detail': 'Document not found.'}, status=status.HTTP_404_NOT_FOUND)

        # One query for the whole thread; the tree is assembled in memory.
        comments = list(self.get_queryset().filter(document_id=document_id).order_by('created_at'))
        children = defaultdict(list)
        top_level = []
        for comment in comments:
            if comment.parent_id is None:
                top_level.append(comment)
            else:
                children[comment.parent_id].append(comment)

        context = {**self.get_serializer_context(), 'children': children}
        return Response(CommentSerializer(top_level, many=True, context=context).data)


class TagViewSet(mixins.CreateModelMixin, viewsets.GenericViewSet):
    """POST /api/tags/    create a tag; names are unique (lower-cased), duplicates return 409."""

    queryset = Tag.objects.all()
    serializer_class = TagSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            return Response(
                {'detail': f'A tag named "{serializer.validated_data["name"]}" already exists.'},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class AuditLogViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    GET /api/audit-logs/?actor=<user id>&from=<date>&to=<date>

    `from` / `to` accept YYYY-MM-DD (whole days, `to` inclusive) or an ISO 8601 datetime.
    Extra filters: `object_id`, `model_name`, and `action` (comma-separated).
    """

    serializer_class = AuditLogSerializer

    def get_queryset(self):
        params = self.request.query_params
        queryset = AuditLog.objects.select_related('actor')

        actor = params.get('actor')
        if actor:
            queryset = queryset.filter(actor_id=parse_uuid_param('actor', actor))

        date_from = params.get('from')
        date_to = params.get('to')
        start = parse_datetime_param('from', date_from) if date_from else None
        end = parse_datetime_param('to', date_to, end_of_day=True) if date_to else None
        if start and end and start > end:
            raise ValidationError({'from': '"from" must not be later than "to".'})
        if start:
            queryset = queryset.filter(timestamp__gte=start)
        if end:
            queryset = queryset.filter(timestamp__lte=end)

        if params.get('object_id'):
            queryset = queryset.filter(object_id=params['object_id'])
        if params.get('model_name'):
            queryset = queryset.filter(model_name__iexact=params['model_name'])
        if params.get('action'):
            queryset = queryset.filter(action__in=parse_csv_param(params['action']))

        return queryset.order_by('-timestamp')
