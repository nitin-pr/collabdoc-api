from django.db import IntegrityError, transaction
from django.db.models import Count
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from common.utils import parse_csv_param
from documents.models import Document
from users.models import User

from .models import Workspace, WorkspaceMember
from .serializers import AddMemberSerializer, WorkspaceMemberSerializer, WorkspaceSerializer


class WorkspaceViewSet(mixins.CreateModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    POST /api/workspaces/                    create a workspace (+ owner as admin, atomically)
    GET  /api/workspaces/{id}/               workspace with member count
    POST /api/workspaces/{id}/members/       add a member with a role
    GET  /api/workspaces/{id}/members/       list members with roles
    GET  /api/workspaces/{id}/summary/       document / member / comment totals
    """

    serializer_class = WorkspaceSerializer

    def get_queryset(self):
        return Workspace.objects.select_related('owner').annotate(member_count=Count('members', distinct=True))

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            # Workspace + its first member must succeed or fail together.
            with transaction.atomic():
                workspace = serializer.save()
                WorkspaceMember.objects.create(
                    workspace=workspace, user=workspace.owner, role=WorkspaceMember.Role.ADMIN
                )
        except IntegrityError:
            return Response(
                {'detail': 'Could not create the workspace because of a data conflict.'},
                status=status.HTTP_409_CONFLICT,
            )
        # Re-read through get_queryset() so the response carries the annotated member_count.
        workspace = self.get_queryset().get(pk=workspace.pk)
        return Response(self.get_serializer(workspace).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get', 'post'], url_path='members')
    def members(self, request, pk=None):
        workspace = self.get_object()
        if request.method == 'POST':
            return self._add_member(request, workspace)
        return self._list_members(request, workspace)

    def _list_members(self, request, workspace):
        queryset = workspace.members.select_related('user').order_by('joined_at')

        roles = request.query_params.get('role')
        if roles:
            wanted = parse_csv_param(roles)
            invalid = [role for role in wanted if role not in WorkspaceMember.Role.values]
            if invalid:
                raise ValidationError({'role': f'Invalid role(s): {", ".join(invalid)}. '
                                               f'Choose from {", ".join(WorkspaceMember.Role.values)}.'})
            queryset = queryset.filter(role__in=wanted)

        return Response(WorkspaceMemberSerializer(queryset, many=True).data)

    def _add_member(self, request, workspace):
        serializer = AddMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not workspace.is_active:
            raise ValidationError({'detail': 'Cannot add members to an inactive workspace.'})

        try:
            user = User.objects.get(pk=serializer.validated_data['user'])
        except User.DoesNotExist:
            return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            with transaction.atomic():
                member = WorkspaceMember.objects.create(
                    workspace=workspace, user=user, role=serializer.validated_data['role']
                )
        except IntegrityError:
            # unique_workspace_member (workspace, user) was violated.
            return Response(
                {'detail': 'User is already a member of this workspace.'},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(WorkspaceMemberSerializer(member).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='summary')
    def summary(self, request, pk=None):
        workspace = self.get_object()

        # One query; distinct=True stops the members x documents x comments joins inflating the counts.
        totals = Workspace.objects.filter(pk=workspace.pk).aggregate(
            member_count=Count('members', distinct=True),
            document_count=Count('documents', distinct=True),
            comment_count=Count('documents__comments', distinct=True),
        )
        by_status = {
            row['status']: row['total']
            for row in Document.objects.filter(workspace=workspace)
            .values('status')
            .annotate(total=Count('id'))
        }

        return Response({
            'workspace': workspace.id,
            'name': workspace.name,
            **totals,
            'documents_by_status': {value: by_status.get(value, 0) for value in Document.Status.values},
        })
