from ninja import Router, File, Form
from ninja.files import UploadedFile
from django.shortcuts import get_object_or_404
from django.http import HttpRequest
from meetings.models import Meeting
from .models import Transcript
from .schemas import (
    TranscriptSchemaIn,
    TranscriptSchemaOut,
    TranscriptStatusSchemaOut,
    ProcessingStatusEnum,
    ErrorDetail
)
from typing import Union, Optional
import logging

from .utils import extract_text, SUPPORTED_CONTENT_TYPES

logger = logging.getLogger(__name__)

router = Router(tags=["Transcripts"])

# --- Endpoint to Submit Transcript (Text or File) ---
@router.post(
    "/meetings/{meeting_id}/transcript",
    response={201: TranscriptSchemaOut, 404: ErrorDetail, 400: ErrorDetail, 409: ErrorDetail, 413: ErrorDetail, 415: ErrorDetail},
    summary="Submit a transcript (JSON text or file upload)",
    description="Upload transcript as JSON `{'raw_text': '...'}` or as a file (`.txt`, `.pdf`, `.docx`)."
)
def submit_transcript(
    request: HttpRequest,
    meeting_id: int,
    payload: Union[TranscriptSchemaIn, None] = Form(None),
    file: UploadedFile = File(None)
):
    meeting = get_object_or_404(Meeting, id=meeting_id)
    if Transcript.objects.filter(meeting=meeting).exists():
        return 409, {"detail": f"Transcript already exists for meeting {meeting_id}."}

    raw_text_content: Optional[str] = None
    uploaded_file_object = None
    if file and payload and payload.raw_text:
        return 400, {"detail": "Provide either 'raw_text' in body OR a 'file', not both."}
    if file:
        uploaded_file_object = file
        try:
            max_size = 20 * 1024 * 1024
            if file.size > max_size:
                 logger.warning(f"File upload rejected (too large): {file.name}, size: {file.size}")
                 return 413, {"detail": f"File size exceeds limit ({max_size // 1024 // 1024}MB)."}
            logger.info(f"Attempting text extraction from file: {file.name}, type: {file.content_type}")
            raw_text_content = extract_text(file)
            logger.info(f"Text extracted successfully from: {file.name}")
        except ValueError as e:
            logger.error(f"Extraction failed for {file.name}: {e}", exc_info=True)
            if "Unsupported file type" in str(e):
                return 415, {"detail": str(e)}
            else:
                return 400, {"detail": f"Error processing file: {e}"}
        except Exception as e:
            logger.error(f"Unexpected error handling file {file.name}: {e}", exc_info=True)
            return 500, {"detail": "An unexpected server error occurred while handling the file."}

    elif payload and payload.raw_text:
        raw_text_content = payload.raw_text
        logger.info(f"Received raw text submission for meeting {meeting_id}")

    else:
        return 400, {"detail": "Please provide either 'raw_text' in the body or upload a 'file'."}

    if not raw_text_content or len(raw_text_content.strip()) < 10:
        logger.warning(f"Transcript text too short or empty for meeting {meeting_id}")
        source = f"from file {file.name}" if file else "from raw text input"
        return 400, {"detail": f"Transcript text is empty or too short (min 10 chars) {source}."}

    try:
        transcript = Transcript(
            meeting=meeting,
            raw_text=raw_text_content,
        )
        if uploaded_file_object:
            transcript.original_file = uploaded_file_object
        transcript.save()
        logger.info(f"Transcript record created: ID {transcript.id} for meeting {meeting_id}")

        return 201, transcript

    except Exception as e:
        logger.error(f"Database error saving transcript for meeting {meeting_id}: {e}", exc_info=True)
        return 500, {"detail": "An error occurred while saving the transcript."}


@router.get(
    "/transcripts/{transcript_id}/status",
    response={200: TranscriptStatusSchemaOut, 404: ErrorDetail},
    summary="Get transcript processing status"
)
def get_transcript_status(request: HttpRequest, transcript_id: int):
    """
    Retrieves the current processing status of a specific transcript.
    """
    transcript = get_object_or_404(Transcript, id=transcript_id)
    logger.debug(f"Fetching status for transcript {transcript_id}")
    return 200, transcript

@router.get(
    "/transcripts/{transcript_id}",
    response={200: TranscriptSchemaOut, 404: ErrorDetail},
    summary="Get full transcript details"
)
def get_transcript_details(request: HttpRequest, transcript_id: int):
    transcript = get_object_or_404(Transcript, id=transcript_id)
    logger.debug(f"Fetching details for transcript {transcript_id}")
    return 200, transcript
