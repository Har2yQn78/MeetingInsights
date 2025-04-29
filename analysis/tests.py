from django.test import TestCase, Client

# Create your tests here.

import json
import uuid
from unittest import mock
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken
from meetings.models import Meeting
from analysis.models import AnalysisResult
from datetime import date, timedelta
from django.core.files.base import ContentFile
from transcripts.models import Transcript
from analysis.tasks import process_transcript_analysis

def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {'access': str(refresh.access_token)}

class MockAsyncResult:
    def __init__(self, task_id):
        self.id = task_id

class AnalysisAPITestCase(TestCase):

    def setUp(self):
        self.client = Client()
        self.test_user = User.objects.create_user(username='analysisuser', password='password123')
        self.tokens = get_tokens_for_user(self.test_user)
        self.auth_headers = {'HTTP_AUTHORIZATION': f'Bearer {self.tokens["access"]}'}
        self.base_url = '/api/analysis/'
        self.meeting = Meeting.objects.create(title="Analysis API Test Meeting")
        self.transcript_done = Transcript.objects.create(meeting=self.meeting, raw_text="Analyzed text.",
                                                         processing_status=Transcript.ProcessingStatus.COMPLETED,
                                                         title="Completed Transcript Title")
        self.analysis_result = AnalysisResult.objects.create(transcript=self.transcript_done, summary="Existing summary",
                                                             key_points=["Existing point"], task="Existing task")
        self.transcript_processing = Transcript.objects.create(meeting=self.meeting, raw_text="Processing text.",
                                                               processing_status=Transcript.ProcessingStatus.PROCESSING,
                                                               async_task_id='processing-task-id')
        self.transcript_failed = Transcript.objects.create(meeting=self.meeting, raw_text="Failed text.",
                                                           processing_status=Transcript.ProcessingStatus.FAILED,
                                                           processing_error="Something went wrong")
        self.transcript_pending_generate = Transcript.objects.create(meeting=self.meeting, raw_text="Ready to generate analysis.",
                                                                     processing_status=Transcript.ProcessingStatus.PENDING)


    def test_get_transcript_analysis_success(self):
        url = f"{self.base_url}transcript/{self.transcript_done.id}/"
        response = self.client.get(url, **self.auth_headers)
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data['transcript_id'], self.transcript_done.id)
        self.assertEqual(response_data['summary'], self.analysis_result.summary)
        self.assertEqual(response_data['key_points'], self.analysis_result.key_points)
        self.assertEqual(response_data['task'], self.analysis_result.task)
        self.assertEqual(response_data['transcript_title'], self.transcript_done.title)


    def test_get_meeting_analysis_success(self):
        transcript2 = Transcript.objects.create(meeting=self.meeting, raw_text="Second", processing_status=Transcript.ProcessingStatus.COMPLETED)
        AnalysisResult.objects.create(transcript=transcript2, summary="Second summary")
        url = f"{self.base_url}meeting/{self.meeting.id}/"
        response = self.client.get(url, **self.auth_headers)
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertIn('count', response_data)
        self.assertIn('items', response_data)
        self.assertEqual(response_data['count'], 2)
        self.assertEqual(len(response_data['items']), 2)
        self.assertEqual(response_data['items'][0]['summary'], "Second summary")
        self.assertEqual(response_data['items'][1]['summary'], self.analysis_result.summary)


    def test_get_meeting_analysis_pagination(self):
        t2 = Transcript.objects.create(meeting=self.meeting, raw_text="t2", processing_status=Transcript.ProcessingStatus.COMPLETED)
        AnalysisResult.objects.create(transcript=t2, summary="s2")
        t3 = Transcript.objects.create(meeting=self.meeting, raw_text="t3", processing_status=Transcript.ProcessingStatus.COMPLETED)
        AnalysisResult.objects.create(transcript=t3, summary="s3")
        url = f"{self.base_url}meeting/{self.meeting.id}/?limit=1&offset=1"
        response = self.client.get(url, **self.auth_headers)
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data['count'], 3)
        self.assertEqual(len(response_data['items']), 1)
        self.assertEqual(response_data['items'][0]['summary'], "s2")

    def test_get_meeting_analysis_meeting_not_found(self):
        non_existent_id = 99999
        url = f"{self.base_url}meeting/{non_existent_id}/"
        response = self.client.get(url, **self.auth_headers)
        self.assertEqual(response.status_code, 404)

    def test_get_meeting_analysis_unauthenticated(self):
        url = f"{self.base_url}meeting/{self.meeting.id}/"
        response = self.client.get(url) # No auth headers
        self.assertEqual(response.status_code, 401)


    @mock.patch('analysis.tasks.process_transcript_analysis.delay')
    def test_generate_analysis_success(self, mock_delay):
        mock_delay.return_value = MockAsyncResult('fake-generate-task-id')
        transcript_id = self.transcript_pending_generate.id
        url = f"{self.base_url}generate/{transcript_id}/"
        response = self.client.post(url, **self.auth_headers)
        self.assertEqual(response.status_code, 202)
        response_data = response.json()
        self.assertEqual(response_data['id'], transcript_id)
        self.assertEqual(response_data['processing_status'], Transcript.ProcessingStatus.PENDING)
        self.assertEqual(response_data['async_task_id'], 'fake-generate-task-id')
        self.transcript_pending_generate.refresh_from_db()
        self.assertEqual(self.transcript_pending_generate.processing_status, Transcript.ProcessingStatus.PENDING)
        self.assertEqual(self.transcript_pending_generate.async_task_id, 'fake-generate-task-id')
        self.assertIsNone(self.transcript_pending_generate.processing_error)
        mock_delay.assert_called_once_with(transcript_id)


    def test_generate_analysis_conflict_completed(self):
        url = f"{self.base_url}generate/{self.transcript_done.id}/"
        response = self.client.post(url, **self.auth_headers)
        self.assertEqual(response.status_code, 409)
        self.assertIn("already been completed", response.json()['detail'])

    def test_generate_analysis_conflict_processing(self):
        url = f"{self.base_url}generate/{self.transcript_processing.id}/"
        response = self.client.post(url, **self.auth_headers)
        self.assertEqual(response.status_code, 409)
        self.assertIn("already in progress", response.json()['detail'])

    def test_generate_analysis_transcript_not_found(self):
        non_existent_id = 99999
        url = f"{self.base_url}generate/{non_existent_id}/"
        response = self.client.post(url, **self.auth_headers)
        self.assertEqual(response.status_code, 404)

    def test_generate_analysis_unauthenticated(self):
        url = f"{self.base_url}generate/{self.transcript_pending_generate.id}/"
        response = self.client.post(url) # No auth headers
        self.assertEqual(response.status_code, 401)

    @mock.patch('analysis.tasks.process_transcript_analysis.delay')
    def test_generate_analysis_bad_request_no_content(self, mock_delay):
         empty_transcript = Transcript.objects.create(meeting=self.meeting, raw_text="", original_file=None,
                                                      processing_status=Transcript.ProcessingStatus.PENDING)
         url = f"{self.base_url}generate/{empty_transcript.id}/"
         response = self.client.post(url, **self.auth_headers)
         self.assertEqual(response.status_code, 400)
         self.assertIn("no text content or file", response.json()['detail'])
         empty_transcript.refresh_from_db()
         self.assertEqual(empty_transcript.processing_status, Transcript.ProcessingStatus.FAILED)
         self.assertIn("no text content or associated file", empty_transcript.processing_error)
         mock_delay.assert_not_called()


MOCK_ANALYSIS_SUCCESS_RESULT = {
    "transcript_title": "Mocked Analysis Title",
    "summary": "This is a mocked summary of the transcript.",
    "key_points": ["Mocked point 1", "Mocked decision A"],
    "task": "Mocked action item",
    "responsible": "Mocked Team",
    "deadline": date.today() + timedelta(days=7)
}

MOCK_ANALYSIS_MINIMAL_RESULT = {
    "transcript_title": None,
    "summary": "Minimal summary.",
    "key_points": [],
    "task": None,
    "responsible": None,
    "deadline": None
}


class AnalysisTaskTestCase(TestCase):

    def setUp(self):
        self.meeting = Meeting.objects.create(title="Analysis Task Meeting")
        self.transcript_pending = Transcript.objects.create(meeting=self.meeting, raw_text="This is the transcript text to be analyzed.",
                                                            processing_status=Transcript.ProcessingStatus.PENDING)
        self.transcript_file = Transcript.objects.create( meeting=self.meeting, raw_text="",  processing_status=Transcript.ProcessingStatus.PENDING)
        self.transcript_file.original_file.save("test_for_task.txt", ContentFile(b"Text content from the file."))
        self.transcript_completed = Transcript.objects.create(meeting=self.meeting, raw_text="Already done.",
                                                              processing_status=Transcript.ProcessingStatus.COMPLETED)
        self.transcript_failed = Transcript.objects.create(meeting=self.meeting, raw_text="Something went wrong before.",
                                                           processing_status=Transcript.ProcessingStatus.FAILED)
        self.transcript_empty = Transcript.objects.create(meeting=self.meeting, raw_text="   ", processing_status=Transcript.ProcessingStatus.PENDING)


    @mock.patch('analysis.tasks.TranscriptAnalysisService.analyze_transcript_sync')
    @mock.patch('analysis.tasks.process_transcript_analysis.request')
    def test_task_success_raw_text(self, mock_request, mock_analyze_sync):
        mock_analyze_sync.return_value = MOCK_ANALYSIS_SUCCESS_RESULT
        mock_request.id = str(uuid.uuid4())
        result = process_transcript_analysis(self.transcript_pending.id)
        self.assertEqual(result['status'], 'success')
        self.transcript_pending.refresh_from_db()
        self.assertEqual(self.transcript_pending.processing_status, Transcript.ProcessingStatus.COMPLETED)
        self.assertEqual(self.transcript_pending.title, MOCK_ANALYSIS_SUCCESS_RESULT['transcript_title'])
        self.assertIsNone(self.transcript_pending.processing_error)
        self.assertEqual(self.transcript_pending.async_task_id, mock_request.id)
        analysis = AnalysisResult.objects.get(transcript=self.transcript_pending)
        self.assertEqual(analysis.summary, MOCK_ANALYSIS_SUCCESS_RESULT['summary'])
        self.assertEqual(analysis.key_points, MOCK_ANALYSIS_SUCCESS_RESULT['key_points'])
        self.assertEqual(analysis.task, MOCK_ANALYSIS_SUCCESS_RESULT['task'])
        self.assertEqual(analysis.responsible, MOCK_ANALYSIS_SUCCESS_RESULT['responsible'])
        self.assertEqual(analysis.deadline, MOCK_ANALYSIS_SUCCESS_RESULT['deadline'])
        mock_analyze_sync.assert_called_once_with(self.transcript_pending.raw_text)


    @mock.patch('analysis.tasks._read_file_sync')
    @mock.patch('analysis.tasks.TranscriptAnalysisService.analyze_transcript_sync')
    @mock.patch('analysis.tasks.process_transcript_analysis.request')
    def test_task_success_from_file(self, mock_request, mock_analyze_sync, mock_read_file):
        mock_analyze_sync.return_value = MOCK_ANALYSIS_SUCCESS_RESULT
        mock_read_file.return_value = "Text content from the file."
        mock_request.id = str(uuid.uuid4())
        result = process_transcript_analysis(self.transcript_file.id)
        self.assertEqual(result['status'], 'success')
        self.transcript_file.refresh_from_db()
        self.assertEqual(self.transcript_file.processing_status, Transcript.ProcessingStatus.COMPLETED)
        self.assertEqual(self.transcript_file.title, MOCK_ANALYSIS_SUCCESS_RESULT['transcript_title'])
        analysis = AnalysisResult.objects.get(transcript=self.transcript_file)
        self.assertEqual(analysis.summary, MOCK_ANALYSIS_SUCCESS_RESULT['summary'])
        mock_read_file.assert_called_once()
        mock_analyze_sync.assert_called_once_with("Text content from the file.")

    @mock.patch('analysis.tasks.TranscriptAnalysisService.analyze_transcript_sync')
    @mock.patch('analysis.tasks.process_transcript_analysis.request')
    def test_task_failure_llm_error(self, mock_request, mock_analyze_sync):
        mock_analyze_sync.side_effect = ConnectionError("LLM unavailable")
        mock_request.id = str(uuid.uuid4())
        process_transcript_analysis(self.transcript_pending.id)
        self.transcript_pending.refresh_from_db()
        self.assertEqual(self.transcript_pending.processing_status, Transcript.ProcessingStatus.FAILED)
        self.assertIn("ConnectionError", self.transcript_pending.processing_error)
        self.assertIn("LLM unavailable", self.transcript_pending.processing_error)
        self.assertFalse(AnalysisResult.objects.filter(transcript=self.transcript_pending).exists())


    @mock.patch('analysis.tasks._read_file_sync')
    @mock.patch('analysis.tasks.TranscriptAnalysisService.analyze_transcript_sync')
    @mock.patch('analysis.tasks.process_transcript_analysis.request')
    def test_task_failure_file_read_error(self, mock_request, mock_analyze_sync, mock_read_file):
        mock_read_file.side_effect = IOError("Disk read error")
        mock_request.id = str(uuid.uuid4())
        result = process_transcript_analysis(self.transcript_file.id)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['reason'], 'File read error')
        self.transcript_file.refresh_from_db()
        self.assertEqual(self.transcript_file.processing_status, Transcript.ProcessingStatus.FAILED)
        self.assertIn("IOError", self.transcript_file.processing_error)
        self.assertIn("Disk read error", self.transcript_file.processing_error)
        mock_read_file.assert_called_once()
        mock_analyze_sync.assert_not_called()

    @mock.patch('analysis.tasks.TranscriptAnalysisService.analyze_transcript_sync')
    def test_task_skip_already_completed(self, mock_analyze_sync):
        result = process_transcript_analysis(self.transcript_completed.id)
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(result['reason'], 'Already completed')
        mock_analyze_sync.assert_not_called()
        self.transcript_completed.refresh_from_db()
        self.assertEqual(self.transcript_completed.processing_status, Transcript.ProcessingStatus.COMPLETED)

    @mock.patch('analysis.tasks.TranscriptAnalysisService.analyze_transcript_sync')
    def test_task_skip_already_failed(self, mock_analyze_sync):
        result = process_transcript_analysis(self.transcript_failed.id)
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(result['reason'], 'Already failed')
        mock_analyze_sync.assert_not_called()
        self.transcript_failed.refresh_from_db()
        self.assertEqual(self.transcript_failed.processing_status, Transcript.ProcessingStatus.FAILED)

    def test_task_transcript_not_found(self):
        non_existent_id = 99999
        result = process_transcript_analysis(non_existent_id)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['reason'], 'Transcript not found')