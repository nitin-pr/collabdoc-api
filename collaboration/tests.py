import uuid
from datetime import datetime, timezone

from django.db import transaction
from rest_framework import status
from rest_framework.test import APITestCase

from common.test_helpers import make_document, make_user, make_workspace
from documents.models import Document

from .models import AuditLog, Comment, Tag

COMMENTS_URL = '/api/comments/'
TAGS_URL = '/api/tags/'
AUDIT_URL = '/api/audit-logs/'
MISSING_ID = '00000000-0000-0000-0000-000000000000'


class CreateCommentTests(APITestCase):
    def setUp(self):
        self.author = make_user(first_name='Asha', last_name='Rao')
        self.document = make_document(created_by=self.author)

    def post(self, **overrides):
        payload = {'document': str(self.document.id), 'author': str(self.author.id),
                   'content': 'Looks good', **overrides}
        return self.client.post(COMMENTS_URL, payload, format='json')

    def test_top_level_comment_returns_201(self):
        response = self.post()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data['parent'])
        self.assertEqual(response.data['author_name'], 'Asha Rao')
        self.assertEqual(response.data['replies'], [])

    def test_reply_returns_201_and_points_at_its_parent(self):
        parent = Comment.objects.create(document=self.document, author=self.author, content='Question?')

        response = self.post(parent=str(parent.id), content='Answer')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()['parent'], str(parent.id))
        self.assertEqual(list(parent.replies.values_list('content', flat=True)), ['Answer'])

    def test_a_reply_can_be_replied_to(self):
        parent = Comment.objects.create(document=self.document, author=self.author, content='a')
        reply = Comment.objects.create(document=self.document, author=self.author, content='b', parent=parent)

        self.assertEqual(self.post(parent=str(reply.id)).status_code, status.HTTP_201_CREATED)

    def test_reply_to_a_comment_on_another_document_returns_400(self):
        other = make_document()
        foreign_parent = Comment.objects.create(document=other, author=self.author, content='elsewhere')

        response = self.post(parent=str(foreign_parent.id))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('parent', response.data)
        self.assertEqual(Comment.objects.filter(content='Looks good').count(), 0)

    def test_blank_content_returns_400(self):
        response = self.post(content='   ')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('content', response.data)

    def test_missing_author_returns_400(self):
        payload = {'document': str(self.document.id), 'content': 'anonymous'}
        response = self.client.post(COMMENTS_URL, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('author', response.data)

    def test_unknown_document_returns_400(self):
        self.assertEqual(self.post(document=MISSING_ID).status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_parent_returns_400(self):
        self.assertEqual(self.post(parent=MISSING_ID).status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_and_delete_are_not_allowed(self):
        comment = Comment.objects.create(document=self.document, author=self.author, content='x')

        self.assertEqual(self.client.put(f'{COMMENTS_URL}{comment.id}/', {}, format='json').status_code,
                         status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.client.delete(f'{COMMENTS_URL}{comment.id}/').status_code, status.HTTP_404_NOT_FOUND)


class ListCommentTests(APITestCase):
    def setUp(self):
        self.author = make_user(first_name='Asha', last_name='Rao')
        self.document = make_document(created_by=self.author)

    def comment(self, content, parent=None, document=None):
        return Comment.objects.create(document=document or self.document, author=self.author,
                                      content=content, parent=parent)

    def get(self, **params):
        return self.client.get(COMMENTS_URL, params)

    def test_comments_are_threaded(self):
        first = self.comment('first')
        reply = self.comment('reply to first', parent=first)
        self.comment('reply to the reply', parent=reply)
        second = self.comment('second')
        self.comment('another reply', parent=second)

        response = self.get(document=self.document.id)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([c['content'] for c in response.data], ['first', 'second'])
        thread = response.data[0]['replies']
        self.assertEqual([c['content'] for c in thread], ['reply to first'])
        self.assertEqual([c['content'] for c in thread[0]['replies']], ['reply to the reply'])
        self.assertEqual([c['content'] for c in response.data[1]['replies']], ['another reply'])

    def test_only_comments_for_the_requested_document_are_returned(self):
        self.comment('mine')
        self.comment('theirs', document=make_document())

        response = self.get(document=self.document.id)

        self.assertEqual([c['content'] for c in response.data], ['mine'])

    def test_document_without_comments_returns_an_empty_list(self):
        self.assertEqual(self.get(document=self.document.id).data, [])

    def test_document_parameter_is_required(self):
        response = self.get()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('document', response.data)

    def test_malformed_document_id_returns_400(self):
        self.assertEqual(self.get(document='abc').status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_document_returns_404(self):
        self.assertEqual(self.get(document=MISSING_ID).status_code, status.HTTP_404_NOT_FOUND)

    def test_the_whole_thread_is_loaded_in_two_queries(self):
        parent = self.comment('root')
        for n in range(5):
            parent = self.comment(f'reply {n}', parent=parent)

        # 1 existence check for the document + 1 for every comment with its author, at any depth.
        with self.assertNumQueries(2):
            self.get(document=self.document.id)


class CreateTagTests(APITestCase):
    def test_create_returns_201(self):
        response = self.client.post(TAGS_URL, {'name': 'python'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'python')
        self.assertTrue(Tag.objects.filter(name='python').exists())

    def test_name_is_trimmed_and_lower_cased(self):
        response = self.client.post(TAGS_URL, {'name': '  Django REST '}, format='json')

        self.assertEqual(response.data['name'], 'django rest')

    def test_duplicate_returns_409(self):
        self.client.post(TAGS_URL, {'name': 'python'}, format='json')
        response = self.client.post(TAGS_URL, {'name': 'python'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn('already exists', response.data['detail'])
        self.assertEqual(Tag.objects.count(), 1)

    def test_duplicate_differing_only_by_case_returns_409(self):
        self.client.post(TAGS_URL, {'name': 'python'}, format='json')

        self.assertEqual(self.client.post(TAGS_URL, {'name': 'PYTHON'}, format='json').status_code,
                         status.HTTP_409_CONFLICT)

    def test_blank_name_returns_400(self):
        self.assertEqual(self.client.post(TAGS_URL, {'name': '  '}, format='json').status_code,
                         status.HTTP_400_BAD_REQUEST)

    def test_missing_name_returns_400(self):
        self.assertEqual(self.client.post(TAGS_URL, {}, format='json').status_code, status.HTTP_400_BAD_REQUEST)

    def test_name_longer_than_100_characters_returns_400(self):
        self.assertEqual(self.client.post(TAGS_URL, {'name': 'x' * 101}, format='json').status_code,
                         status.HTTP_400_BAD_REQUEST)

    def test_only_creation_is_exposed(self):
        self.assertEqual(self.client.get(TAGS_URL).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class AuditLogListTests(APITestCase):
    def setUp(self):
        self.alice = make_user(first_name='Alice', last_name='A')
        self.bob = make_user(first_name='Bob', last_name='B')
        self.old = self.log(self.alice, 'created', datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc))
        self.mid = self.log(self.bob, 'updated', datetime(2026, 9, 15, 23, 30, tzinfo=timezone.utc))
        self.new = self.log(self.alice, 'updated', datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc))

    def log(self, actor, action, when):
        entry = AuditLog.objects.create(actor=actor, action=action, model_name='Document', object_id=str(uuid.uuid4()))
        AuditLog.objects.filter(pk=entry.pk).update(timestamp=when)  # auto_now_add ignores values passed in
        return entry

    def ids(self, **params):
        response = self.client.get(AUDIT_URL, params)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return [entry['id'] for entry in response.data]

    def test_lists_everything_newest_first(self):
        self.assertEqual(self.ids(), [str(self.new.id), str(self.mid.id), str(self.old.id)])

    def test_filter_by_actor(self):
        self.assertEqual(self.ids(actor=self.bob.id), [str(self.mid.id)])

    def test_filter_from(self):
        self.assertEqual(self.ids(**{'from': '2026-09-15'}), [str(self.new.id), str(self.mid.id)])

    def test_filter_to_includes_the_whole_last_day(self):
        # mid happened at 23:30 on the 15th, so `to=2026-09-15` must still include it.
        self.assertEqual(self.ids(to='2026-09-15'), [str(self.mid.id), str(self.old.id)])

    def test_filter_date_range(self):
        self.assertEqual(self.ids(**{'from': '2026-09-10', 'to': '2026-09-30'}), [str(self.mid.id)])

    def test_filter_with_iso_datetimes(self):
        self.assertEqual(self.ids(**{'from': '2026-09-15T23:00:00Z', 'to': '2026-09-15T23:59:59Z'}),
                         [str(self.mid.id)])

    def test_filters_combine(self):
        self.assertEqual(self.ids(actor=self.alice.id, **{'from': '2026-09-15'}), [str(self.new.id)])

    def test_filter_by_action_and_object(self):
        self.assertEqual(self.ids(action='created'), [str(self.old.id)])
        self.assertEqual(self.ids(object_id=self.mid.object_id), [str(self.mid.id)])

    def test_response_names_the_actor(self):
        response = self.client.get(AUDIT_URL, {'actor': self.alice.id})

        self.assertEqual(response.data[0]['actor_name'], 'Alice A')
        self.assertEqual(response.data[0]['model_name'], 'Document')

    def test_malformed_actor_returns_400(self):
        response = self.client.get(AUDIT_URL, {'actor': 'abc'})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('actor', response.data)

    def test_malformed_dates_return_400(self):
        for params in ({'from': 'yesterday'}, {'to': '2026-13-45'}, {'from': '2026-10-01T99:00:00'}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(AUDIT_URL, params).status_code, status.HTTP_400_BAD_REQUEST)

    def test_from_after_to_returns_400(self):
        response = self.client.get(AUDIT_URL, {'from': '2026-10-01', 'to': '2026-09-01'})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_actor_returns_an_empty_list(self):
        self.assertEqual(self.ids(actor=MISSING_ID), [])

    def test_actors_are_loaded_with_select_related(self):
        with self.assertNumQueries(1):
            self.client.get(AUDIT_URL)

    def test_audit_logs_are_read_only(self):
        self.assertEqual(self.client.post(AUDIT_URL, {}, format='json').status_code,
                         status.HTTP_405_METHOD_NOT_ALLOWED)


class DocumentAuditSignalTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.workspace = make_workspace(owner=self.author)

    def new_document(self):
        return Document.objects.create(title='T', content='C', workspace=self.workspace, created_by=self.author)

    def test_creating_a_document_writes_a_created_entry(self):
        document = self.new_document()

        log = AuditLog.objects.get()
        self.assertEqual((log.action, log.model_name, log.object_id, log.actor),
                         ('created', 'Document', str(document.id), self.author))

    def test_saving_again_writes_an_updated_entry(self):
        document = self.new_document()
        document.content = 'changed'
        document.save()

        self.assertEqual(list(AuditLog.objects.order_by('timestamp').values_list('action', flat=True)),
                         ['created', 'updated'])

    def test_one_entry_per_save(self):
        document = self.new_document()
        for _ in range(3):
            document.save()

        self.assertEqual(AuditLog.objects.filter(object_id=str(document.id)).count(), 4)

    def test_other_models_do_not_write_audit_entries(self):
        Tag.objects.create(name='x')
        Comment.objects.create(document=self.new_document(), author=self.author, content='c')

        self.assertEqual(AuditLog.objects.count(), 1)  # only the document's own 'created'

    def test_audit_entry_is_rolled_back_with_the_document(self):
        try:
            with transaction.atomic():
                self.new_document()
                raise RuntimeError('fail after the write')
        except RuntimeError:
            pass

        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_actor_survives_as_null_when_the_user_is_deleted(self):
        self.new_document()
        self.author.delete()

        # Deleting the author cascades to the workspace and document they owned; the audit trail stays.
        self.assertEqual(AuditLog.objects.count(), 1)
        self.assertIsNone(AuditLog.objects.get().actor)
