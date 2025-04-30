from typing import List, Optional
from django.shortcuts import get_object_or_404
from django.db import transaction
from ninja import Router, File
from ninja.files import UploadedFile
from ninja_jwt.authentication import JWTAuth
import logging
from .models import Transcript, Meeting
from .schemas import TranscriptSchemaIn, TranscriptSchemaOut, TranscriptStatusSchemaOut, ErrorDetail
from analysis.tasks import process_transcript_analysis

router = Router(tags=["transcripts"])
logger = logging.getLogger(__name__)

@router.post("/{meeting_id}/", response={201: TranscriptSchemaOut, 400: ErrorDetail, 404: ErrorDetail}, auth=JWTAuth(),
             summary="Submit Raw Text Transcript",
             description="""
             Creates a new transcript record associated with a specific meeting by submitting raw text content.

             **Workflow:**
             1. Associates the provided `raw_text` with the specified `meeting_id`.
             2. Creates a `Transcript` database entry with status `PENDING`.
             3. **Asynchronously queues** an analysis task (`process_transcript_analysis`) via Celery to process the text.
             4. Saves the Celery task ID to the transcript record for tracking.

             **Details:**
             - Requires authentication via JWT.
             - Uses the `meeting_id` provided in the URL path.
             - Expects a JSON payload conforming to `TranscriptSchemaIn` (containing the `raw_text`).
             - Operations (Transcript creation, task queueing) are performed within an atomic database transaction for consistency.

             **On Success:** Returns `201 Created` with the initial transcript details (including its ID and `PENDING` status) conforming to
              `TranscriptSchemaOut`. The actual analysis results must be fetched later after processing completes.
             **On Failure:**
                 - Returns `404 Not Found` if the specified `meeting_id` does not exist.
                 - Returns `400 Bad Request` if input validation fails, the task queueing fails, or another error occurs during creation.
                  If task queueing fails after the initial record creation attempt, the transcript status might be set to `FAILED`.
             """
             )
def create_transcript(request, meeting_id: int, data: TranscriptSchemaIn):
    try:
        meeting = get_object_or_404(Meeting, id=meeting_id)
    except Meeting.DoesNotExist:
        return 404, {"detail": f"Meeting with id {meeting_id} not found"}

    transcript = None
    try:
        with transaction.atomic():
            transcript = Transcript.objects.create(meeting=meeting, raw_text=data.raw_text, processing_status=Transcript.ProcessingStatus.PENDING)
            logger.info(f"Created Transcript {transcript.id} for Meeting {meeting_id}. Queueing analysis task.")
            task = process_transcript_analysis.delay(transcript.id)
            transcript.async_task_id = task.id
            transcript.save(update_fields=['async_task_id'])
            logger.info(f"Transcript {transcript.id} queued for analysis with task ID: {task.id}")

        return 201, transcript
    except Exception as e:
        logger.error(f"Error creating transcript or queueing task for meeting {meeting_id}: {e}", exc_info=True)
        if transcript and transcript.pk and not transcript.async_task_id:
             try:
                 transcript.processing_status = Transcript.ProcessingStatus.FAILED
                 transcript.processing_error = f"Failed during task queueing: {str(e)}"
                 transcript.save(update_fields=['processing_status', 'processing_error'])
                 logger.warning(f"Marked Transcript {transcript.id} as FAILED due to task queueing error.")
             except Exception as update_err:
                  logger.error(f"Failed to mark transcript {transcript.id} as FAILED after queueing error: {update_err}")
        return 400, {"detail": f"Failed to create transcript or queue analysis task: {str(e)}"}


@router.post("/{meeting_id}/upload/", response={201: TranscriptSchemaOut, 400: ErrorDetail, 404: ErrorDetail}, auth=JWTAuth(),
             summary="Upload Transcript File",
             description="""
             Creates a new transcript record associated with a specific meeting by uploading a file 
             (e.g., TXT, PDF, DOCX - supported types depend on the background task configuration).

             **Workflow:**
             1. Associates the uploaded `file` with the specified `meeting_id`.
             2. Creates a `Transcript` database entry, saving the file reference. The `raw_text` field is initially empty. Status is set to `PENDING`.
             3. **Asynchronously queues** an analysis task (`process_transcript_analysis`) via Celery. This task is responsible for extracting text from
              the file and performing the analysis.
             4. Saves the Celery task ID to the transcript record for tracking.

             **Details:**
             - Requires authentication via JWT.
             - Uses the `meeting_id` provided in the URL path.
             - Expects the file upload via multipart/form-data under the field name `file`.
             - Operations (Transcript creation, task queueing) are performed within an atomic database transaction.

             **On Success:** Returns `201 Created` with the initial transcript details (including its ID and `PENDING` status) conforming to `TranscriptSchemaOut`.
              File processing and analysis happen asynchronously.
             **On Failure:**
                 - Returns `404 Not Found` if the specified `meeting_id` does not exist.
                 - Returns `400 Bad Request` if the file upload fails, task queueing fails, or another error occurs. If task queueing fails after the initial
                  record creation attempt, the transcript status might be set to `FAILED`.
             """
             )
def upload_transcript_file(request, meeting_id: int, file: UploadedFile = File(...)):
    try:
        meeting = get_object_or_404(Meeting, id=meeting_id)
    except Meeting.DoesNotExist:
        return 404, {"detail": f"Meeting with id {meeting_id} not found"}

    transcript = None
    try:
        with transaction.atomic():
            transcript = Transcript.objects.create(meeting=meeting, original_file=file, raw_text="", processing_status=Transcript.ProcessingStatus.PENDING)
            logger.info(f"Created Transcript {transcript.id} via file upload ({file.name}) for Meeting {meeting_id}. Queueing analysis task.")
            task = process_transcript_analysis.delay(transcript.id)
            transcript.async_task_id = task.id
            transcript.save(update_fields=['async_task_id'])
            logger.info(f"Transcript {transcript.id} queued for analysis with task ID: {task.id}")

        return 201, transcript
    except Exception as e:
        logger.error(f"Error uploading transcript file or queueing task for meeting {meeting_id}: {e}", exc_info=True)
        if transcript and transcript.pk and not transcript.async_task_id:
             try:
                 transcript.processing_status = Transcript.ProcessingStatus.FAILED
                 transcript.processing_error = f"Failed during task queueing after upload: {str(e)}"
                 transcript.save(update_fields=['processing_status', 'processing_error'])
                 logger.warning(f"Marked Transcript {transcript.id} as FAILED due to task queueing error after upload.")
             except Exception as update_err:
                  logger.error(f"Failed to mark transcript {transcript.id} as FAILED after queueing error (upload): {update_err}")
        return 400, {"detail": f"Failed to process file upload or queue analysis task: {str(e)}"}


@router.get("/status/{transcript_id}/", response={200: TranscriptStatusSchemaOut, 404: ErrorDetail}, auth=JWTAuth(),
            summary="Get Transcript Processing Status",
            description="""
            Retrieves the current processing status and basic details of a specific transcript.

            **Purpose:** This endpoint is designed for clients (like the Streamlit UI) to poll and check the progress of the asynchronous analysis
             task initiated by transcript submission or upload.

            **Details:**
            - Requires authentication via JWT.
            - Uses the `transcript_id` provided in the URL path.
            - Optimized to fetch only essential status-related fields (`id`, `meeting_id`, `processing_status`, `processing_error`, `updated_at`, etc.)
             from the database.

            **Response Fields:**
            - `processing_status`: Indicates the current state (e.g., `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`).
            - `processing_error`: Contains an error message if the status is `FAILED`.

            **On Success:** Returns `200 OK` with the status details conforming to `TranscriptStatusSchemaOut`.
            **On Failure:** Returns `404 Not Found` if no transcript exists with the specified `transcript_id`.
            """
            )
def get_transcript_status(request, transcript_id: int):
    try:
        transcript = get_object_or_404(Transcript.objects.only('id', 'meeting_id', 'processing_status',
                                                               'processing_error', 'original_file', 'updated_at', 'async_task_id'),
                                       id=transcript_id)
        return 200, transcript
    except Transcript.DoesNotExist:
        return 404, {"detail": f"Transcript with id {transcript_id} not found"}


@router.get("/{transcript_id}/", response={200: TranscriptSchemaOut, 404: ErrorDetail}, auth=JWTAuth(),
            summary="Get Transcript Details",
            description="""
            Retrieves the full details of a specific transcript record, including its raw text (if available) and processing status.

            **Details:**
            - Requires authentication via JWT.
            - Uses the `transcript_id` provided in the URL path.

            **On Success:** Returns `200 OK` with the complete transcript details conforming to `TranscriptSchemaOut`.
            **On Failure:** Returns `404 Not Found` if no transcript exists with the specified `transcript_id`.
            """
            )
def get_transcript(request, transcript_id: int):
    try:
        transcript = get_object_or_404(Transcript, id=transcript_id)
        return 200, transcript
    except Transcript.DoesNotExist:
        return 404, {"detail": f"Transcript with id {transcript_id} not found"}


@router.get("/meeting/{meeting_id}/", response=List[TranscriptSchemaOut], auth=JWTAuth(),
            summary="List Transcripts for a Meeting",
            description="""
            Retrieves a list of all transcripts associated with a specific meeting.

            **Details:**
            - Requires authentication via JWT.
            - Uses the `meeting_id` provided in the URL path to identify the meeting.
            - Returns transcripts ordered by creation date (most recent first).
            - Does not currently support pagination; returns all transcripts for the meeting.

            **On Success:** Returns `200 OK` with a list of transcript details, each conforming to `TranscriptSchemaOut`.
             The list will be empty if the meeting has no transcripts.
            **On Failure:** Returns `404 Not Found` implicitly if the specified `meeting_id` does not correspond to an existing meeting.
            """
            )
def get_meeting_transcripts(request, meeting_id: int):
    get_object_or_404(Meeting, id=meeting_id)
    transcripts = Transcript.objects.filter(meeting_id=meeting_id).order_by('-created_at')
    return transcripts