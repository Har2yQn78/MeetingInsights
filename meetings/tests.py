from django.test import TestCase, Client

# Create your tests here.

import json
from datetime import datetime, timedelta
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Meeting
def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {'access': str(refresh.access_token)}

class BasicMeetingAPITestCase(TestCase):

    def setUp(self):
        self.client = Client()
        self.test_user = User.objects.create_user(username='testuser', password='password123')
        self.tokens = get_tokens_for_user(self.test_user)
        self.auth_headers = {'HTTP_AUTHORIZATION': f'Bearer {self.tokens["access"]}'}
        self.base_url = '/api/meetings/'
        self.existing_meeting = Meeting.objects.create(title="Initial Meeting", meeting_date=timezone.now(), participants=["Alice"])

    def test_create_meeting_success(self):
        url = self.base_url
        data = {"title": "New Test Meeting","participants": ["Bob"],}
        response = self.client.post(url, data=json.dumps(data), content_type='application/json', **self.auth_headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['title'], data['title'])
        self.assertTrue(Meeting.objects.filter(title=data['title']).exists())

    def test_list_meetings_success(self):
        url = self.base_url
        response = self.client.get(url, **self.auth_headers)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)
        titles = [m['title'] for m in response.json()]
        self.assertIn(self.existing_meeting.title, titles)


    def test_get_meeting_success(self):
        url = f"{self.base_url}{self.existing_meeting.id}/"
        response = self.client.get(url, **self.auth_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['id'], self.existing_meeting.id)
        self.assertEqual(response.json()['title'], self.existing_meeting.title)

    def test_update_meeting_success(self):
        url = f"{self.base_url}{self.existing_meeting.id}/"
        update_data = {"title": "Updated Meeting Title"}
        response = self.client.put(url, data=json.dumps(update_data), content_type='application/json', **self.auth_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['title'], update_data['title'])
        self.existing_meeting.refresh_from_db()
        self.assertEqual(self.existing_meeting.title, update_data['title'])

    def test_delete_meeting_success(self):
        url = f"{self.base_url}{self.existing_meeting.id}/"
        response = self.client.delete(url, **self.auth_headers)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Meeting.objects.filter(id=self.existing_meeting.id).exists())

    def test_unauthenticated_access_fails(self):
        url = self.base_url
        response = self.client.get(url)
        self.assertEqual(response.status_code, 401)

    def test_create_meeting_invalid_title_fails(self):
        url = self.base_url
        data = {"title": "  ", "participants": ["Test"]}
        response = self.client.post(url, data=json.dumps(data), content_type='application/json', **self.auth_headers)
        self.assertIn(response.status_code, [400, 422])
        self.assertIn('detail', response.json())