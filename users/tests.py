from rest_framework import status
from rest_framework.test import APITestCase

from .models import User

USERS_URL = '/api/users/'
MISSING_ID = '00000000-0000-0000-0000-000000000000'


class UserApiTests(APITestCase):
    def setUp(self):
        self.payload = {
            'first_name': 'Asha',
            'last_name': 'Rao',
            'email': 'asha@example.com',
            'phone': '9876543210',
        }

    def create_user(self, **overrides):
        return User.objects.create(**{**self.payload, **overrides})

    def test_create_user_returns_201(self):
        response = self.client.post(USERS_URL, self.payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['email'], 'asha@example.com')
        self.assertTrue(User.objects.filter(id=response.data['id']).exists())

    def test_create_user_normalises_email(self):
        payload = {**self.payload, 'email': '  Asha@Example.COM '}
        response = self.client.post(USERS_URL, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['email'], 'asha@example.com')

    def test_duplicate_email_returns_409(self):
        self.create_user()
        payload = {**self.payload, 'phone': '9123456780'}
        response = self.client.post(USERS_URL, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn('already exists', response.data['detail'])
        self.assertEqual(User.objects.count(), 1)

    def test_duplicate_phone_returns_409(self):
        self.create_user()
        payload = {**self.payload, 'email': 'other@example.com'}
        response = self.client.post(USERS_URL, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(User.objects.count(), 1)

    def test_duplicate_email_differing_only_by_case_returns_409(self):
        self.create_user()
        payload = {**self.payload, 'email': 'ASHA@EXAMPLE.COM', 'phone': '9123456780'}
        response = self.client.post(USERS_URL, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_invalid_email_returns_400(self):
        for email in ('not-an-email', 'a@b', '@example.com', 'a@.com', 'a@example.'):
            with self.subTest(email=email):
                payload = {**self.payload, 'email': email}
                response = self.client.post(USERS_URL, payload, format='json')

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn('email', response.data)

    def test_invalid_phone_returns_400(self):
        for phone in ('abc', '12345', '12345678901234567', '98765-43210', '98765 43210'):
            with self.subTest(phone=phone):
                payload = {**self.payload, 'phone': phone}
                response = self.client.post(USERS_URL, payload, format='json')

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn('phone', response.data)

    def test_phone_with_leading_plus_is_accepted(self):
        payload = {**self.payload, 'phone': '+919876543210'}
        response = self.client.post(USERS_URL, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_missing_fields_return_400(self):
        response = self.client.post(USERS_URL, {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        for field in ('first_name', 'last_name', 'email', 'phone'):
            self.assertIn(field, response.data)

    def test_client_cannot_set_id_or_created_at(self):
        forced_id = '11111111-1111-1111-1111-111111111111'
        payload = {**self.payload, 'id': forced_id, 'created_at': '2000-01-01T00:00:00Z'}
        response = self.client.post(USERS_URL, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(response.data['id'], forced_id)
        self.assertFalse(response.data['created_at'].startswith('2000'))

    def test_retrieve_user_returns_200(self):
        user = self.create_user()
        response = self.client.get(f'{USERS_URL}{user.id}/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(user.id))
        self.assertEqual(response.data['first_name'], 'Asha')

    def test_retrieve_unknown_id_returns_404(self):
        response = self.client.get(f'{USERS_URL}{MISSING_ID}/')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_malformed_id_returns_404(self):
        response = self.client.get(f'{USERS_URL}not-a-uuid/')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_only_create_and_retrieve_are_allowed(self):
        user = self.create_user()
        detail_url = f'{USERS_URL}{user.id}/'

        self.assertEqual(self.client.get(USERS_URL).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(self.client.put(detail_url, self.payload, format='json').status_code,
                         status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(self.client.patch(detail_url, {}, format='json').status_code,
                         status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(self.client.delete(detail_url).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
