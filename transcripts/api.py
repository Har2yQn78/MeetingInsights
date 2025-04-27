from typing import List, Optional
from django.shortcuts import get_object_or_404
from django.db import transaction
from ninja import Router, File
from ninja.files import UploadedFile
from ninja_jwt.authentication import JWTAuth
import logging

from .models import Transcript, Meeting
from .schemas import TranscriptSchemaIn, TranscriptSchemaOut, TranscriptStatusSchemaOut, ErrorDetail
from analysis.task import process_transcript_analysis

router = Router(tags=["transcripts"])
logger = logging.getLogger(__name__)

@router.post("/{meeting_id}/", response={201: TranscriptSchemaOut, 400: ErrorDetail, 404: ErrorDetail}, auth=JWTAuth())
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


@router.post("/{meeting_id}/upload/", response={201: TranscriptSchemaOut, 400: ErrorDetail, 404: ErrorDetail}, auth=JWTAuth())
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


@router.get("/status/{transcript_id}/", response={200: TranscriptStatusSchemaOut, 404: ErrorDetail}, auth=JWTAuth())
def get_transcript_status(request, transcript_id: int):
    try:
        transcript = get_object_or_404(Transcript.objects.only('id', 'meeting_id', 'processing_status',
                                                               'processing_error', 'original_file', 'updated_at', 'async_task_id'),
                                       id=transcript_id)
        return 200, transcript
    except Transcript.DoesNotExist:
        return 404, {"detail": f"Transcript with id {transcript_id} not found"}


@router.get("/{transcript_id}/", response={200: TranscriptSchemaOut, 404: ErrorDetail}, auth=JWTAuth())
def get_transcript(request, transcript_id: int):
    try:
        transcript = get_object_or_404(Transcript, id=transcript_id)
        return 200, transcript
    except Transcript.DoesNotExist:
        return 404, {"detail": f"Transcript with id {transcript_id} not found"}


@router.get("/meeting/{meeting_id}/", response=List[TranscriptSchemaOut], auth=JWTAuth())
def get_meeting_transcripts(request, meeting_id: int):
    get_object_or_404(Meeting, id=meeting_id)
    transcripts = Transcript.objects.filter(meeting_id=meeting_id).order_by('-created_at')
    return transcripts