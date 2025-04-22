# transcripts/api.py
from typing import List, Optional
from django.shortcuts import get_object_or_404
from django.db import transaction
from ninja import Router, File
from ninja.files import UploadedFile
from ninja_jwt.authentication import JWTAuth

from .models import Transcript, Meeting
from .schemas import TranscriptSchemaIn, TranscriptSchemaOut, TranscriptStatusSchemaOut, ErrorDetail

# Create router for transcripts
router = Router(tags=["transcripts"])


@router.post("/{meeting_id}/", response={201: TranscriptSchemaOut, 400: ErrorDetail, 404: ErrorDetail}, auth=JWTAuth())
def create_transcript(request, meeting_id: int, data: TranscriptSchemaIn):
    try:
        # Check if meeting exists
        meeting = get_object_or_404(Meeting, id=meeting_id)

        # Create transcript
        transcript = Transcript.objects.create(
            meeting=meeting,
            raw_text=data.raw_text,
            processing_status=Transcript.ProcessingStatus.PENDING
        )

        # Here you would typically trigger your async processing task
        # Example: process_transcript_task.delay(transcript.id)

        return 201, transcript
    except Meeting.DoesNotExist:
        return 404, {"detail": f"Meeting with id {meeting_id} not found"}
    except Exception as e:
        return 400, {"detail": str(e)}


@router.post("/{meeting_id}/upload/", response={201: TranscriptSchemaOut, 400: ErrorDetail, 404: ErrorDetail},
             auth=JWTAuth())
def upload_transcript_file(request, meeting_id: int, file: UploadedFile = File(...)):
    try:
        # Check if meeting exists
        meeting = get_object_or_404(Meeting, id=meeting_id)

        # Create transcript with file upload
        transcript = Transcript.objects.create(
            meeting=meeting,
            original_file=file,
            processing_status=Transcript.ProcessingStatus.PENDING
        )

        # Here you would typically trigger your async processing task
        # Example: process_transcript_file_task.delay(transcript.id)

        return 201, transcript
    except Meeting.DoesNotExist:
        return 404, {"detail": f"Meeting with id {meeting_id} not found"}
    except Exception as e:
        return 400, {"detail": str(e)}


@router.get("/status/{transcript_id}/", response={200: TranscriptStatusSchemaOut, 404: ErrorDetail}, auth=JWTAuth())
def get_transcript_status(request, transcript_id: int):
    try:
        transcript = get_object_or_404(Transcript, id=transcript_id)
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
    return Transcript.objects.filter(meeting_id=meeting_id).order_by('-created_at')