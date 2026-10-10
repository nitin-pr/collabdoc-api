import uuid
from unittest import mock

from django.db import IntegrityError
from rest_framework import status
from rest_framework.test import APITestCase

from collaboration.models import Comment
from common.test_helpers import make_document, make_user, make_workspace

from .models import Workspace, WorkspaceMember

WORKSPACES_URL = '/api/workspaces/'
MISSING_ID = '00000000-0000-0000-0000-000000000000'


class CreateWorkspaceTests(APITestCase):
    def setUp(self):
        self.owner = make_user(first_name='Asha', last_name='Rao')

    def post(self, **overrides):
        payload = {'name': 'Engineering', 'owner': str(self.owner.id), **overrides}
        return self.client.post(WORKSPACES_URL, payload, format='json')

    def test_create_returns_201_with_member_count_and_owner_name(self):
        response = self.post()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'Engineering')
        self.assertEqual(response.data['member_count'], 1)
        self.assertEqual(response.data['owner_name'], 'Asha Rao')
        self.assertTrue(response.data['is_active'])

    def test_owner_is_added_as_admin_member(self):
        response = self.post()

        member = WorkspaceMember.objects.get(workspace_id=response.data['id'])
        self.assertEqual(member.user, self.owner)
        self.assertEqual(member.role, WorkspaceMember.Role.ADMIN)

    def test_name_is_stripped(self):
        self.assertEqual(self.post(name='  Padded  ').data['name'], 'Padded')

    def test_blank_name_returns_400(self):
        response = self.post(name='   ')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('name', response.data)

    def test_unknown_owner_returns_400(self):
        response = self.post(owner=MISSING_ID)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('owner', response.data)

    def test_missing_fields_return_400(self):
        response = self.client.post(WORKSPACES_URL, {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('name', response.data)
        self.assertIn('owner', response.data)

    def test_failure_while_adding_the_owner_rolls_back_the_workspace(self):
        with mock.patch.object(WorkspaceMember, 'save', side_effect=IntegrityError('boom')):
            response = self.post()

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(Workspace.objects.count(), 0)
        self.assertEqual(WorkspaceMember.objects.count(), 0)


class RetrieveWorkspaceTests(APITestCase):
    def test_returns_workspace_with_member_count(self):
        workspace = make_workspace()
        WorkspaceMember.objects.create(workspace=workspace, user=make_user())

        response = self.client.get(f'{WORKSPACES_URL}{workspace.id}/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['member_count'], 2)

    def test_unknown_id_returns_404(self):
        self.assertEqual(self.client.get(f'{WORKSPACES_URL}{MISSING_ID}/').status_code, status.HTTP_404_NOT_FOUND)

    def test_malformed_id_returns_404(self):
        self.assertEqual(self.client.get(f'{WORKSPACES_URL}not-a-uuid/').status_code, status.HTTP_404_NOT_FOUND)

    def test_detail_uses_a_single_query(self):
        workspace = make_workspace()

        with self.assertNumQueries(1):
            self.client.get(f'{WORKSPACES_URL}{workspace.id}/')


class AddMemberTests(APITestCase):
    def setUp(self):
        self.workspace = make_workspace()
        self.url = f'{WORKSPACES_URL}{self.workspace.id}/members/'
        self.user = make_user()

    def post(self, **overrides):
        return self.client.post(self.url, {'user': str(self.user.id), 'role': 'editor', **overrides}, format='json')

    def test_add_member_returns_201_with_nested_user(self):
        response = self.post()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['role'], 'editor')
        self.assertEqual(response.data['user']['id'], str(self.user.id))
        self.assertTrue(WorkspaceMember.objects.filter(workspace=self.workspace, user=self.user).exists())

    def test_role_defaults_to_viewer(self):
        response = self.client.post(self.url, {'user': str(self.user.id)}, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['role'], 'viewer')

    def test_adding_the_same_user_twice_returns_409(self):
        self.post()
        response = self.post(role='admin')

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn('already a member', response.data['detail'])
        self.assertEqual(self.workspace.members.filter(user=self.user).count(), 1)

    def test_adding_the_owner_again_returns_409(self):
        response = self.post(user=str(self.workspace.owner_id))

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_unknown_user_returns_404(self):
        response = self.post(user=MISSING_ID)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['detail'], 'User not found.')

    def test_invalid_role_returns_400(self):
        response = self.post(role='superuser')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('role', response.data)

    def test_malformed_user_id_returns_400(self):
        self.assertEqual(self.post(user='abc').status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_user_returns_400(self):
        response = self.client.post(self.url, {'role': 'viewer'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('user', response.data)

    def test_unknown_workspace_returns_404(self):
        response = self.client.post(f'{WORKSPACES_URL}{MISSING_ID}/members/', {'user': str(self.user.id)}, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_inactive_workspace_returns_400(self):
        Workspace.objects.filter(pk=self.workspace.pk).update(is_active=False)

        self.assertEqual(self.post().status_code, status.HTTP_400_BAD_REQUEST)


class ListMembersTests(APITestCase):
    def setUp(self):
        self.workspace = make_workspace()
        self.editor = make_user()
        self.viewer = make_user()
        WorkspaceMember.objects.create(workspace=self.workspace, user=self.editor, role='editor')
        WorkspaceMember.objects.create(workspace=self.workspace, user=self.viewer, role='viewer')
        self.url = f'{WORKSPACES_URL}{self.workspace.id}/members/'

    def test_lists_members_with_roles_and_nested_users(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([m['role'] for m in response.data], ['admin', 'editor', 'viewer'])
        self.assertEqual(response.data[1]['user']['email'], self.editor.email)

    def test_filter_by_role(self):
        response = self.client.get(self.url, {'role': 'editor,viewer'})

        self.assertEqual([m['role'] for m in response.data], ['editor', 'viewer'])

    def test_invalid_role_filter_returns_400(self):
        self.assertEqual(self.client.get(self.url, {'role': 'boss'}).status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_workspace_returns_404(self):
        self.assertEqual(self.client.get(f'{WORKSPACES_URL}{MISSING_ID}/members/').status_code,
                         status.HTTP_404_NOT_FOUND)

    def test_users_are_loaded_with_select_related(self):
        # 1 query for the workspace + 1 for all members and their users, however many members there are.
        with self.assertNumQueries(2):
            self.client.get(self.url)


class WorkspaceSummaryTests(APITestCase):
    def test_summary_counts_documents_members_and_comments(self):
        owner = make_user()
        workspace = make_workspace(owner=owner)
        WorkspaceMember.objects.create(workspace=workspace, user=make_user())
        first = make_document(workspace, owner, status='draft')
        second = make_document(workspace, owner, status='published')
        make_document()  # a document in a different workspace must not be counted
        for document in (first, first, second):
            Comment.objects.create(document=document, author=owner, content='hi')

        response = self.client.get(f'{WORKSPACES_URL}{workspace.id}/summary/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['member_count'], 2)
        self.assertEqual(response.data['document_count'], 2)
        self.assertEqual(response.data['comment_count'], 3)
        self.assertEqual(response.data['documents_by_status'], {'draft': 1, 'published': 1, 'archived': 0})

    def test_empty_workspace_has_zero_counts(self):
        workspace = make_workspace()

        response = self.client.get(f'{WORKSPACES_URL}{workspace.id}/summary/')

        self.assertEqual(response.data['member_count'], 1)
        self.assertEqual(response.data['document_count'], 0)
        self.assertEqual(response.data['comment_count'], 0)

    def test_unknown_workspace_returns_404(self):
        self.assertEqual(self.client.get(f'{WORKSPACES_URL}{uuid.uuid4()}/summary/').status_code,
                         status.HTTP_404_NOT_FOUND)
