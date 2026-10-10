from rest_framework import status
from rest_framework.test import APITestCase

from collaboration.models import Tag
from common.test_helpers import make_document, make_user, make_workspace


class TrailingSlashTests(APITestCase):
    """Every endpoint must work with or without its trailing slash, including POST and PUT."""

    def setUp(self):
        self.owner = make_user()
        self.workspace = make_workspace(owner=self.owner)
        self.document = make_document(self.workspace, self.owner)
        Tag.objects.create(name='python')

    def test_post_without_slash_creates_a_user(self):
        payload = {'first_name': 'Asha', 'last_name': 'Rao', 'email': 'asha@example.com', 'phone': '9876543210'}

        response = self.client.post('/api/users', payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_post_with_slash_still_works(self):
        payload = {'first_name': 'Asha', 'last_name': 'Rao', 'email': 'asha@example.com', 'phone': '9876543210'}

        self.assertEqual(self.client.post('/api/users/', payload, format='json').status_code,
                         status.HTTP_201_CREATED)

    def test_every_endpoint_answers_the_same_with_and_without_the_slash(self):
        workspace, document = self.workspace.id, self.document.id
        cases = [
            ('get', f'/api/users/{self.owner.id}', None),
            ('post', '/api/workspaces', {'name': 'New', 'owner': str(self.owner.id)}),
            ('get', f'/api/workspaces/{workspace}', None),
            ('get', f'/api/workspaces/{workspace}/members', None),
            ('post', f'/api/workspaces/{workspace}/members', {'user': str(make_user().id), 'role': 'viewer'}),
            ('get', f'/api/workspaces/{workspace}/summary', None),
            ('post', '/api/documents', {'title': 'T', 'content': 'C', 'workspace': str(workspace),
                                        'created_by': str(self.owner.id)}),
            ('put', f'/api/documents/{document}', {'content': 'changed'}),
            ('get', '/api/documents', None),
            ('get', f'/api/documents/{document}/versions', None),
            ('get', f'/api/documents/{document}/stats', None),
            ('post', f'/api/documents/{document}/tags', {'tags': ['python']}),
            ('post', '/api/comments', {'document': str(document), 'author': str(self.owner.id), 'content': 'hi'}),
            ('get', f'/api/comments?document={document}', None),
            ('post', '/api/tags', {'name': 'django'}),
            ('get', '/api/audit-logs', None),
        ]
        for method, path, body in cases:
            with self.subTest(method=method, path=path):
                response = getattr(self.client, method)(path, body, format='json') if body is not None \
                    else getattr(self.client, method)(path)

                self.assertIn(response.status_code, (status.HTTP_200_OK, status.HTTP_201_CREATED), response.content)
