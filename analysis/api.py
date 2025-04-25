from datetime import datetime
from typing import List, Optional
from django.shortcuts import get_object_or_404
from django.http import Http404, JsonResponse
from django.db import transaction
from django.core.files.base import ContentFile
from ninja import Router, File, UploadedFile, Form, Schema
from asgiref.sync import sync_to_async
import logging
from transcripts.models import Transcript
from meetings.models import Meeting
from .models import AnalysisResult
from transcripts.schemas import TranscriptStatusSchemaOut
from .schemas import AnalysisResultSchemaOut, ErrorDetail, DirectProcessInput
from .task import process_transcript_analysis

router = Router(tags=["analysis"])
logger = logging.getLogger(__name__)

@router.get("/transcript/{transcript_id}/", response={200: AnalysisResultSchemaOut, 404: ErrorDetail, 503: ErrorDetail})
async def get_transcript_analysis(request, transcript_id: int):
    try:
        analysis = await sync_to_async(get_object_or_404)(
            AnalysisResult.objects.select_related('transcript', 'transcript__meeting'),
            transcript_id=transcript_id
        )
        return 200, analysis
    except Http404:
        transcript_exists = await sync_to_async(Transcript.objects.filter(id=transcript_id).values('id', 'processing_status').first)()
        if transcript_exists:
            status = transcript_exists['processing_status']
            if status == Transcript.ProcessingStatus.PENDING or status == Transcript.ProcessingStatus.PROCESSING:
                return 503, {"detail": f"Analysis for transcript {transcript_id} is currently processing (Status: {status}). Please try again later."}
            elif status == Transcript.ProcessingStatus.FAILED:
                 return 404, {"detail": f"Analysis for transcript {transcript_id} failed. Check status endpoint for details."}
            else:
                 return 404, {"detail": f"Analysis for transcript {transcript_id} not found, and transcript status is '{status}'."}
        else:
             return 404, {"detail": f"Transcript with id {transcript_id} not found."}
    except Exception as e:
        logger.error(f"Error getting analysis for transcript {transcript_id}: {e}", exc_info=True)
        return 500, {"detail": "An internal server error occurred"}


@router.get("/meeting/{meeting_id}/", response=List[AnalysisResultSchemaOut])
async def get_meeting_analysis(request, meeting_id: int):
    results = await sync_to_async(list)(AnalysisResult.objects.filter( transcript__meeting_id=meeting_id).
                                        select_related('transcript', 'transcript__meeting').order_by('-created_at'))
    return results

@router.post("/generate/{transcript_id}/", response={202: TranscriptStatusSchemaOut, 400: ErrorDetail, 404: ErrorDetail, 409: ErrorDetail}, tags=["analysis", "async"])
async def generate_analysis(request, transcript_id: int):

    transcript = await get_transcript_for_analysis(transcript_id)
    if transcript is None:
        return 404, {"detail": f"Transcript with id {transcript_id} not found"}
    if transcript.processing_status == Transcript.ProcessingStatus.COMPLETED:
         return 409, {"detail": f"Analysis for transcript {transcript_id} has already been completed."}
    if transcript.processing_status == Transcript.ProcessingStatus.PROCESSING:
         return 409, {"detail": f"Analysis for transcript {transcript_id} is already in progress."}
    transcript_text = transcript.raw_text
    has_file = await sync_to_async(lambda: bool(transcript.original_file))()
    if not transcript_text and not has_file:
        logger.warning(f"Attempted to analyze transcript {transcript_id} with no text or file.")

        return 400, {"detail": f"Transcript {transcript_id} has no text content or file to analyze."}

    try:
        logger.info(f"Queueing analysis task for transcript {transcript_id} via generate endpoint.")
        task = process_transcript_analysis.delay(transcript.id)
        await sync_to_async(Transcript.objects.filter(id=transcript.id).update)(
            processing_status=Transcript.ProcessingStatus.PENDING,
            async_task_id=task.id,
            processing_error=None
        )
        logger.info(f"Transcript {transcript_id} status set to PENDING, task ID: {task.id}")

        updated_transcript = await get_transcript_for_analysis(transcript_id)
        return 202, updated_transcript

    except Exception as e:
        logger.error(f"Error queueing analysis task for transcript {transcript_id}: {e}", exc_info=True)
        await sync_to_async(Transcript.objects.filter(id=transcript.id).update)(
             processing_status=Transcript.ProcessingStatus.FAILED,
             processing_error=f"Failed to queue analysis task: {str(e)}"
         )
        return 500, {"detail": f"An unexpected error occurred while queueing the analysis task: {str(e)}"}

@router.post(
    "/process/direct/",
    response={202: TranscriptStatusSchemaOut, 400: ErrorDetail, 500: ErrorDetail},
    summary="Submit transcript text/file, create meeting/transcript, and queue for analysis.",
    tags=["analysis", "async"]
)
async def direct_process_transcript(request, payload: DirectProcessInput = Form(None), file: Optional[UploadedFile] = File(None)):
    transcript_text = None
    file_content = None
    original_filename = None
    source_type = None

    if payload and payload.raw_text:
        transcript_text = payload.raw_text
        source_type = 'text'
        logger.info("Processing direct submission with raw text.")
    elif file:
        try:
            file_content = await file.read()
            original_filename = file.name
            try:
                transcript_text = file_content.decode('utf-8')
                logger.info(f"Processing direct submission with file: {original_filename} (decoded as UTF-8)")
            except UnicodeDecodeError:
                 logger.warning(f"Could not decode file {original_filename} as UTF-8. Storing raw text as empty, analysis will rely on file.")
                 transcript_text = ""
            source_type = 'file'
        except Exception as e:
            logger.error(f"Error reading uploaded file '{file.name if file else 'N/A'}': {e}", exc_info=True)
            return 400, {"detail": f"Could not read uploaded file: {e}"}
    else:
        logger.warning("Direct process endpoint called without raw_text or file.")
        return 400, {"detail": "Please provide either 'raw_text' in the form data or upload a 'file'."}

    if not (transcript_text and transcript_text.strip()) and not file_content:
         logger.warning(f"Direct process submission provided empty content (source: {source_type}).")
         return 400, {"detail": "Transcript content cannot be empty if no file is provided."}

    try:
        placeholder_title = f"Meeting (Processing {datetime.now().strftime('%Y%m%d_%H%M%S')})"
        placeholder_date = datetime.now()

        @sync_to_async(thread_sensitive=True)
        def create_meeting_and_transcript_sync():
            with transaction.atomic():
                meeting = Meeting.objects.create(
                    title=placeholder_title,
                    meeting_date=placeholder_date,
                    participants=[] # Placeholder
                )
                logger.info(f"Created placeholder Meeting ID: {meeting.id}")

                transcript = Transcript(
                    meeting=meeting,
                    raw_text=transcript_text,
                    processing_status=Transcript.ProcessingStatus.PENDING,
                )

                if source_type == 'file' and file_content and original_filename:
                    transcript.original_file.save(
                        original_filename,
                        ContentFile(file_content),
                        save=False
                    )
                    logger.info(f"Attached original file '{original_filename}' to transcript.")

                transcript.save()
                logger.info(f"Created Transcript ID: {transcript.id} for Meeting ID: {meeting.id}")
                return transcript

        transcript = await create_meeting_and_transcript_sync()

        logger.info(f"Queueing analysis task for newly created transcript {transcript.id}")
        task = process_transcript_analysis.delay(transcript.id)

        transcript.async_task_id = task.id
        await sync_to_async(transcript.save)(update_fields=['async_task_id'])
        logger.info(f"Transcript {transcript.id} task ID set to {task.id}")
        return 202, transcript

    except Exception as e:
        logger.error(f"Unexpected error during direct processing submission: {e}", exc_info=True)
        return 500, {"detail": f"An unexpected internal error occurred during submission: {str(e)}"}


@sync_to_async
def get_transcript_for_analysis(transcript_id: int) -> Optional[Transcript]:
     try:
         return Transcript.objects.select_related('meeting').get(id=transcript_id)
     except Transcript.DoesNotExist:
         return None
     except Exception as e:
         logger.error(f"Unexpected error fetching transcript {transcript_id}: {e}", exc_info=True)
         return None