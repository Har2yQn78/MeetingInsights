from django.test import TestCase, Client

# Create your tests here.

import json
from unittest import mock
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework_simplejwt.tokens import RefreshToken
from meetings.models import Meeting
from .models import Transcript

def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {'access': str(refresh.access_token)}

class MockAsyncResult:
    def __init__(self, task_id):
        self.id = task_id

class BasicTranscriptAPITestCase(TestCase):

    def setUp(self):
        self.client = Client()
        self.test_user = User.objects.create_user(username='transcriptuser', password='password123')
        self.tokens = get_tokens_for_user(self.test_user)
        self.auth_headers = {'HTTP_AUTHORIZATION': f'Bearer {self.tokens["access"]}'}
        self.base_url = '/api/transcripts/'
        self.meeting = Meeting.objects.create(title="Transcript Test Meeting", meeting_date=timezone.now())
        self.transcript = Transcript.objects.create(meeting=self.meeting, raw_text="This is existing text.",
                                                    processing_status=Transcript.ProcessingStatus.COMPLETED,
                                                    async_task_id='existing-task-id')

    @mock.patch('analysis.tasks.process_transcript_analysis.delay')
    def test_create_transcript_raw_text_success(self, mock_delay):
        mock_delay.return_value = MockAsyncResult('fake-task-id-raw')
        url = f"{self.base_url}{self.meeting.id}/"
        data = {"raw_text": "This is the raw text for the new transcript."}
        response = self.client.post(url, data=json.dumps(data), content_type='application/json', **self.auth_headers)
        self.assertEqual(response.status_code, 201)
        response_data = response.json()
        self.assertEqual(response_data['meeting_id'], self.meeting.id)
        self.assertEqual(response_data['raw_text'], data['raw_text'])
        self.assertEqual(response_data['processing_status'], Transcript.ProcessingStatus.PENDING)
        self.assertEqual(response_data['async_task_id'], 'fake-task-id-raw')
        mock_delay.assert_called_once()
        self.assertTrue(Transcript.objects.filter(id=response_data['id'], async_task_id='fake-task-id-raw').exists())

    def test_create_transcript_raw_text_meeting_not_found(self):
        non_existent_meeting_id = 9999
        url = f"{self.base_url}{non_existent_meeting_id}/"
        data = {"raw_text": "This text won't be saved."}
        response = self.client.post(url, data=json.dumps(data), content_type='application/json', **self.auth_headers)
        self.assertEqual(response.status_code, 404)
        self.assertIn('detail', response.json())


    @mock.patch('analysis.tasks.process_transcript_analysis.delay')
    def test_upload_transcript_file_success(self, mock_delay):
        mock_delay.return_value = MockAsyncResult('fake-task-id-upload')
        url = f"{self.base_url}{self.meeting.id}/upload/"
        dummy_file_content = b"Content of the uploaded file."
        dummy_file = SimpleUploadedFile("test_transcript.txt", dummy_file_content, content_type="text/plain")
        response = self.client.post(url, data={'file': dummy_file}, **self.auth_headers)
        self.assertEqual(response.status_code, 201)
        response_data = response.json()
        self.assertEqual(response_data['meeting_id'], self.meeting.id)
        self.assertEqual(response_data['processing_status'], Transcript.ProcessingStatus.PENDING)
        self.assertIsNotNone(response_data['original_file_url'])
        self.assertTrue(response_data['original_file_url'].endswith('test_transcript.txt'))
        self.assertEqual(response_data['async_task_id'], 'fake-task-id-upload')
        mock_delay.assert_called_once()
        transcript_id = response_data['id']
        self.assertTrue(Transcript.objects.filter(id=transcript_id, async_task_id='fake-task-id-upload').exists())
        created_transcript = Transcript.objects.get(id=transcript_id)
        self.assertTrue(created_transcript.original_file.name.endswith('test_transcript.txt'))
        self.assertEqual(created_transcript.raw_text, "")


    def test_upload_transcript_file_meeting_not_found(self):
        non_existent_meeting_id = 9999
        url = f"{self.base_url}{non_existent_meeting_id}/upload/"
        dummy_file = SimpleUploadedFile("test.txt", b"content", content_type="text/plain")
        response = self.client.post( url, data={'file': dummy_file}, **self.auth_headers)
        self.assertEqual(response.status_code, 404)
        self.assertIn('detail', response.json())

    def test_get_transcript_status_success(self):
        url = f"{self.base_url}status/{self.transcript.id}/"
        response = self.client.get(url, **self.auth_headers)
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data['id'], self.transcript.id)
        self.assertEqual(response_data['meeting_id'], self.meeting.id)
        self.assertEqual(response_data['processing_status'], self.transcript.processing_status)
        self.assertEqual(response_data['async_task_id'], self.transcript.async_task_id)


    def test_get_transcript_status_not_found(self):
        non_existent_transcript_id = 9999
        url = f"{self.base_url}status/{non_existent_transcript_id}/"
        response = self.client.get(url, **self.auth_headers)
        self.assertEqual(response.status_code, 404)


    def test_get_meeting_transcripts_success(self):
        Transcript.objects.create(meeting=self.meeting, raw_text="Second transcript.")
        url = f"{self.base_url}meeting/{self.meeting.id}/"
        response = self.client.get(url, **self.auth_headers)
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertIsInstance(response_data, list)
        self.assertEqual(len(response_data), 2)
        transcript_ids = [t['id'] for t in response_data]
        self.assertIn(self.transcript.id, transcript_ids)

    def test_get_meeting_transcripts_meeting_not_found(self):
        non_existent_meeting_id = 9999
        url = f"{self.base_url}meeting/{non_existent_meeting_id}/"
        response = self.client.get(url, **self.auth_headers)
        self.assertEqual(response.status_code, 404)
