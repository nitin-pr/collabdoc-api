import uuid

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from collaboration.models import AuditLog, Comment, Tag
from common.test_helpers import make_document, make_user, make_workspace

from .models import Document, DocumentVersion

DOCUMENTS_URL = '/api/documents/'
MISSING_ID = '00000000-0000-0000-0000-000000000000'


class CreateDocumentTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.workspace = make_workspace(owner=self.author)

    def post(self, **overrides):
        payload = {
            'title': 'Roadmap',
            'content': 'Q4 plans',
            'workspace': str(self.workspace.id),
            'created_by': str(self.author.id),
            **overrides,
        }
        return self.client.post(DOCUMENTS_URL, payload, format='json')

    def test_create_returns_201_and_defaults_to_draft(self):
        response = self.post()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'draft')
        self.assertEqual(response.data['version_count'], 1)
        self.assertEqual(response.data['tag_names'], [])

    def test_create_saves_version_one_with_a_snapshot_of_the_content(self):
        response = self.post()

        version = DocumentVersion.objects.get(document_id=response.data['id'])
        self.assertEqual(version.version_number, 1)
        self.assertEqual(version.content, 'Q4 plans')
        self.assertEqual(version.saved_by, self.author)

    def test_create_writes_a_created_audit_log_through_the_signal(self):
        response = self.post()

        log = AuditLog.objects.get(object_id=response.data['id'])
        self.assertEqual(log.action, 'created')
        self.assertEqual(log.model_name, 'Document')
        self.assertEqual(log.actor, self.author)

    def test_blank_title_returns_400(self):
        response = self.post(title='   ')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('title', response.data)

    def test_missing_created_by_returns_400(self):
        payload = {'title': 'T', 'content': 'C', 'workspace': str(self.workspace.id)}
        response = self.client.post(DOCUMENTS_URL, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('created_by', response.data)

    def test_unknown_workspace_returns_400(self):
        self.assertEqual(self.post(workspace=MISSING_ID).status_code, status.HTTP_400_BAD_REQUEST)

    def test_inactive_workspace_returns_400(self):
        self.workspace.is_active = False
        self.workspace.save()

        response = self.post()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('workspace', response.data)
        self.assertEqual(Document.objects.count(), 0)

    def test_invalid_status_returns_400(self):
        self.assertEqual(self.post(status='deleted').status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(DEBUG=True)
    def test_simulated_failure_rolls_back_document_version_and_audit_log(self):
        response = self.post(simulate_failure=True)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('rolled back', response.data['detail'])
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(DocumentVersion.objects.count(), 0)
        self.assertEqual(AuditLog.objects.count(), 0)

    @override_settings(DEBUG=False)
    def test_simulated_failure_is_refused_outside_debug(self):
        response = self.post(simulate_failure=True)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('simulate_failure', response.data)
        self.assertEqual(Document.objects.count(), 0)


class UpdateDocumentTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.editor = make_user()
        self.document = make_document(created_by=self.author)
        self.url = f'{DOCUMENTS_URL}{self.document.id}/'

    def put(self, **overrides):
        payload = {'content': 'second draft', 'saved_by': str(self.editor.id), **overrides}
        return self.client.put(self.url, payload, format='json')

    def test_update_returns_200_and_changes_the_document(self):
        response = self.put(title='Renamed', status='published')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['content'], 'second draft')
        self.assertEqual(response.data['title'], 'Renamed')
        self.assertEqual(response.data['status'], 'published')
        self.assertEqual(response.data['version_count'], 2)

    def test_update_saves_the_next_version_for_this_document(self):
        self.put()

        versions = list(self.document.versions.order_by('version_number'))
        self.assertEqual([v.version_number for v in versions], [1, 2])
        self.assertEqual(versions[0].content, 'first draft')
        self.assertEqual(versions[1].content, 'second draft')
        self.assertEqual(versions[1].saved_by, self.editor)

    def test_every_save_creates_a_new_version_even_when_nothing_changed(self):
        self.put(content='same')
        self.put(content='same')

        self.assertEqual(self.document.versions.count(), 3)

    def test_version_numbers_are_counted_per_document(self):
        other = make_document()
        self.put()

        self.assertEqual(other.versions.count(), 1)
        self.assertEqual(self.document.versions.count(), 2)

    def test_update_writes_an_updated_audit_log(self):
        self.put()

        actions = list(AuditLog.objects.filter(object_id=str(self.document.id)).order_by('timestamp')
                       .values_list('action', flat=True))
        self.assertEqual(actions, ['created', 'updated'])

    def test_workspace_and_author_cannot_be_changed(self):
        other_workspace = make_workspace()
        self.put(workspace=str(other_workspace.id), created_by=str(self.editor.id))

        self.document.refresh_from_db()
        self.assertNotEqual(self.document.workspace_id, other_workspace.id)
        self.assertEqual(self.document.created_by, self.author)

    def test_saved_by_is_optional(self):
        response = self.client.put(self.url, {'content': 'anonymous edit'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(self.document.versions.get(version_number=2).saved_by)

    def test_blank_content_returns_400_and_saves_nothing(self):
        response = self.put(content='  ')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('content', response.data)
        self.assertEqual(self.document.versions.count(), 1)

    def test_missing_content_returns_400(self):
        self.assertEqual(self.client.put(self.url, {'title': 'x'}, format='json').status_code,
                         status.HTTP_400_BAD_REQUEST)

    def test_invalid_status_returns_400(self):
        self.assertEqual(self.put(status='deleted').status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_saved_by_returns_400(self):
        self.assertEqual(self.put(saved_by=MISSING_ID).status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_document_returns_404(self):
        response = self.client.put(f'{DOCUMENTS_URL}{MISSING_ID}/', {'content': 'x'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_malformed_document_id_returns_404(self):
        response = self.client.put(f'{DOCUMENTS_URL}not-a-uuid/', {'content': 'x'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_and_delete_are_not_allowed(self):
        self.assertEqual(self.client.patch(self.url, {}, format='json').status_code,
                         status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(self.client.delete(self.url).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    @override_settings(DEBUG=True)
    def test_simulated_failure_rolls_back_the_update(self):
        response = self.put(content='should not survive', simulate_failure=True)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.document.refresh_from_db()
        self.assertEqual(self.document.content, 'first draft')
        self.assertEqual(self.document.versions.count(), 1)
        self.assertEqual(AuditLog.objects.filter(object_id=str(self.document.id)).count(), 1)


class RetrieveAndListDocumentTests(APITestCase):
    def setUp(self):
        self.owner = make_user()
        self.workspace = make_workspace(owner=self.owner)
        self.other_workspace = make_workspace()
        self.notes = make_document(self.workspace, self.owner, title='Meeting notes', content='budget talk',
                                   status='draft')
        self.plan = make_document(self.workspace, self.owner, title='Launch plan', content='timeline',
                                  status='published')
        self.old = make_document(self.workspace, self.owner, title='Old spec', content='legacy', status='archived')
        self.elsewhere = make_document(self.other_workspace, title='Elsewhere', content='budget')
        python = Tag.objects.create(name='python')
        django = Tag.objects.create(name='django')
        python.documents.add(self.notes, self.plan)
        django.documents.add(self.plan)

    def titles(self, **params):
        response = self.client.get(DOCUMENTS_URL, params)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return {doc['title'] for doc in response.data}

    def test_retrieve_returns_the_document(self):
        response = self.client.get(f'{DOCUMENTS_URL}{self.plan.id}/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Launch plan')
        self.assertEqual(response.data['tag_names'], ['django', 'python'])

    def test_retrieve_unknown_returns_404(self):
        self.assertEqual(self.client.get(f'{DOCUMENTS_URL}{MISSING_ID}/').status_code, status.HTTP_404_NOT_FOUND)

    def test_list_returns_everything_without_filters(self):
        self.assertEqual(len(self.titles()), 4)

    def test_filter_by_workspace(self):
        self.assertEqual(self.titles(workspace=self.workspace.id), {'Meeting notes', 'Launch plan', 'Old spec'})

    def test_filter_by_status(self):
        self.assertEqual(self.titles(status='published'), {'Launch plan'})

    def test_filter_by_several_statuses(self):
        self.assertEqual(self.titles(workspace=self.workspace.id, status='draft,archived'),
                         {'Meeting notes', 'Old spec'})

    def test_filter_by_tag_is_case_insensitive(self):
        self.assertEqual(self.titles(tag='PYTHON'), {'Meeting notes', 'Launch plan'})

    def test_filter_by_several_tags_matches_any_without_duplicates(self):
        response = self.client.get(DOCUMENTS_URL, {'tag': 'python,django'})

        self.assertEqual(len(response.data), 2)

    def test_search_matches_title_or_content(self):
        self.assertEqual(self.titles(search='budget'), {'Meeting notes', 'Elsewhere'})
        self.assertEqual(self.titles(search='LAUNCH'), {'Launch plan'})

    def test_filters_combine(self):
        self.assertEqual(self.titles(workspace=self.workspace.id, tag='python', status='draft'), {'Meeting notes'})

    def test_no_match_returns_an_empty_list(self):
        self.assertEqual(self.titles(search='zzz-nothing'), set())

    def test_malformed_workspace_filter_returns_400(self):
        response = self.client.get(DOCUMENTS_URL, {'workspace': 'abc'})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('workspace', response.data)

    def test_invalid_status_filter_returns_400(self):
        self.assertEqual(self.client.get(DOCUMENTS_URL, {'status': 'deleted'}).status_code,
                         status.HTTP_400_BAD_REQUEST)

    def test_list_query_count_does_not_grow_with_the_number_of_documents(self):
        # 1 query for the documents (with workspace, author and version count) + 1 prefetch for the tags.
        with self.assertNumQueries(2):
            self.client.get(DOCUMENTS_URL)


class DocumentVersionsTests(APITestCase):
    def test_versions_are_listed_oldest_first(self):
        author = make_user()
        document = make_document(created_by=author)
        for text in ('v2 text', 'v3 text'):
            self.client.put(f'{DOCUMENTS_URL}{document.id}/', {'content': text, 'saved_by': str(author.id)},
                            format='json')

        response = self.client.get(f'{DOCUMENTS_URL}{document.id}/versions/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([v['version_number'] for v in response.data], [1, 2, 3])
        self.assertEqual([v['content'] for v in response.data], ['first draft', 'v2 text', 'v3 text'])
        self.assertEqual(response.data[0]['saved_by_name'], f'{author.first_name} {author.last_name}')

    def test_versions_of_unknown_document_returns_404(self):
        self.assertEqual(self.client.get(f'{DOCUMENTS_URL}{MISSING_ID}/versions/').status_code,
                         status.HTTP_404_NOT_FOUND)

    def test_versions_load_users_with_select_related(self):
        document = make_document()
        with self.assertNumQueries(2):  # the document + all versions with their users
            self.client.get(f'{DOCUMENTS_URL}{document.id}/versions/')


class DocumentStatsTests(APITestCase):
    def test_stats_count_versions_comments_and_distinct_contributors(self):
        author, editor = make_user(), make_user()
        document = make_document(created_by=author)
        for user in (editor, editor, author):  # v2, v3, v4 -> only two distinct people saved anything
            self.client.put(f'{DOCUMENTS_URL}{document.id}/', {'content': 'edit', 'saved_by': str(user.id)},
                            format='json')
        for _ in range(3):
            Comment.objects.create(document=document, author=author, content='note')
        tag = Tag.objects.create(name='stats')
        tag.documents.add(document)

        response = self.client.get(f'{DOCUMENTS_URL}{document.id}/stats/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['version_count'], 4)
        self.assertEqual(response.data['comment_count'], 3)
        self.assertEqual(response.data['contributor_count'], 2)
        self.assertEqual(response.data['tag_count'], 1)
        self.assertEqual(response.data['latest_version'], 4)

    def test_stats_for_a_fresh_document(self):
        document = make_document()

        response = self.client.get(f'{DOCUMENTS_URL}{document.id}/stats/')

        self.assertEqual(response.data['version_count'], 1)
        self.assertEqual(response.data['comment_count'], 0)
        self.assertEqual(response.data['contributor_count'], 1)

    def test_stats_of_unknown_document_returns_404(self):
        self.assertEqual(self.client.get(f'{DOCUMENTS_URL}{MISSING_ID}/stats/').status_code,
                         status.HTTP_404_NOT_FOUND)


class DocumentTagsTests(APITestCase):
    def setUp(self):
        self.document = make_document()
        self.url = f'{DOCUMENTS_URL}{self.document.id}/tags/'
        self.python = Tag.objects.create(name='python')
        self.django = Tag.objects.create(name='django')

    def test_add_tags_by_name(self):
        response = self.client.post(self.url, {'tags': ['python', 'django']}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['tags'], ['django', 'python'])
        self.assertEqual(set(self.document.tags.all()), {self.python, self.django})

    def test_add_tags_by_id_and_name_together(self):
        response = self.client.post(self.url, {'tags': [str(self.python.id), 'Django']}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['tags'], ['django', 'python'])

    def test_a_single_tag_can_be_sent_as_a_string(self):
        response = self.client.post(self.url, {'tags': 'python'}, format='json')

        self.assertEqual(response.data['tags'], ['python'])

    def test_adding_the_same_tag_twice_is_harmless(self):
        self.client.post(self.url, {'tags': ['python']}, format='json')
        response = self.client.post(self.url, {'tags': ['python']}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.document.tags.count(), 1)

    def test_unknown_tag_returns_404_and_attaches_nothing(self):
        response = self.client.post(self.url, {'tags': ['python', 'ghost', str(uuid.uuid4())]}, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(len(response.data['missing']), 2)
        self.assertEqual(self.document.tags.count(), 0)

    def test_empty_list_returns_400(self):
        self.assertEqual(self.client.post(self.url, {'tags': []}, format='json').status_code,
                         status.HTTP_400_BAD_REQUEST)

    def test_missing_tags_returns_400(self):
        self.assertEqual(self.client.post(self.url, {}, format='json').status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_document_returns_404(self):
        response = self.client.post(f'{DOCUMENTS_URL}{MISSING_ID}/tags/', {'tags': ['python']}, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
