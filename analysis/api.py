from datetime import datetime
from typing import List, Optional
from django.shortcuts import get_object_or_404
from django.http import Http404, JsonResponse
from django.db import transaction
from django.core.files.base import ContentFile
from ninja import Router, File, UploadedFile, Form, Schema
from ninja_jwt.authentication import JWTAuth
from asgiref.sync import sync_to_async
import logging
from transcripts.models import Transcript
from meetings.models import Meeting
from .models import AnalysisResult
from transcripts.schemas import TranscriptStatusSchemaOut
from .schemas import AnalysisResultSchemaOut, ErrorDetail, DirectProcessInput, PaginatedAnalysisResponse
from .tasks import process_transcript_analysis
from .auth import AsyncJWTAuth

router = Router(tags=["analysis"])
logger = logging.getLogger(__name__)

@router.get("/transcript/{transcript_id}/", response={200: AnalysisResultSchemaOut, 404: ErrorDetail, 503: ErrorDetail},
             summary="Get Analysis Results for Transcript", # Added summary
             description="""
             Retrieves the completed analysis results (summary, key points, action items) for a specific transcript.

             **Behavior:**
             - This endpoint checks if an `AnalysisResult` exists for the given `transcript_id`.
             - **If analysis is complete:** Returns `200 OK` with the analysis details conforming to `AnalysisResultSchemaOut`.
             - **If analysis is PENDING or PROCESSING:** Returns `503 Service Unavailable` with a message indicating the analysis is
              not yet ready and the client should try again later. This prevents polling clients from receiving a misleading 404 while processing is ongoing.
             - **If analysis FAILED:** Returns `404 Not Found` with a message indicating the failure 
             (users should check the transcript status endpoint for error details).
             - **If the transcript itself doesn't exist:** Returns `404 Not Found`.

             **Details:**
             - This is an asynchronous endpoint (uses `async def`).
             - Does **not** require authentication by default in the provided code snippet (no `auth=` argument shown).
              Consider adding `auth=AsyncJWTAuth()` if access should be restricted.
             - Uses the `transcript_id` provided in the URL path.
             """
             )
async def get_transcript_analysis(request, transcript_id: int):
    try:
        analysis = await sync_to_async(get_object_or_404)(AnalysisResult.objects.select_related('transcript'), transcript_id=transcript_id)
        return 200, analysis
    except Http404:
         transcript_info = await sync_to_async(
            Transcript.objects.filter(id=transcript_id).values('id', 'processing_status').first())()
         if transcript_info:
            status = transcript_info['processing_status']
            if status in [Transcript.ProcessingStatus.PENDING, Transcript.ProcessingStatus.PROCESSING]:
                return 503, {"detail": f"Analysis for transcript {transcript_id} is currently processing (Status: {status}). Please try again later."}
            elif status == Transcript.ProcessingStatus.FAILED:
                 return 404, {"detail": f"Analysis for transcript {transcript_id} failed. Check transcript status endpoint for details."}
            else:
                 return 404, {"detail": f"Analysis results for transcript {transcript_id} not found, and transcript status is '{status}'."}
         else:
             return 404, {"detail": f"Transcript with id {transcript_id} not found."}
    except Exception as e:
        logger.error(f"Error getting analysis for transcript {transcript_id}: {e}", exc_info=True)
        return 500, {"detail": "An internal server error occurred while fetching analysis results."}



@router.get("/meeting/{meeting_id}/", response={200: PaginatedAnalysisResponse, 404: ErrorDetail}, auth=AsyncJWTAuth(),
            summary="List Analysis Results for Meeting", # Added summary
            description="""
            Retrieves a paginated list of completed analysis results for all transcripts associated with a specific meeting.

            **Details:**
            - Requires authentication via JWT (using asynchronous authentication).
            - Uses the `meeting_id` provided in the URL path.
            - Returns analysis results ordered by creation date (most recent first).
            - Supports pagination via `offset` and `limit` query parameters.

            **Pagination Query Parameters:**
            - `offset`: The number of analysis results to skip (default: 0).
            - `limit`: The maximum number of analysis results to return per page (default: 5).

            **Response Format:**
            - Conforms to `PaginatedAnalysisResponse`, including `count`, `offset`, `limit`, and a list of `items` (each conforming to `AnalysisResultSchemaOut`).

            **On Success:** Returns `200 OK` with the paginated list of analysis results.
            **On Failure:** Returns `404 Not Found` if the specified `meeting_id` does not correspond to an existing meeting.
            """
            )
async def get_meeting_analysis(request, meeting_id: int, offset: int = 0, limit: int = 5):
    await sync_to_async(get_object_or_404)(Meeting, id=meeting_id)
    results_qs = AnalysisResult.objects.filter(transcript__meeting_id=meeting_id).select_related('transcript').order_by('-created_at')
    total_count = await sync_to_async(results_qs.count)()
    items_list = await sync_to_async(list)(results_qs[offset : offset + limit])
    return PaginatedAnalysisResponse(count=total_count, offset=offset, limit=limit, items=items_list)

@router.post("/generate/{transcript_id}/", response={202: TranscriptStatusSchemaOut, 400: ErrorDetail, 404: ErrorDetail, 409: ErrorDetail}, tags=["analysis", "async"], auth=AsyncJWTAuth(),
             summary="Trigger/Re-trigger Transcript Analysis", # Added summary
             description="""
             Manually triggers (or re-triggers) the asynchronous analysis task for a specific transcript.

             **Use Cases:**
             - Initiate analysis if it wasn't triggered automatically on submission.
             - Re-run analysis if the previous attempt failed.
             - Re-run analysis if the underlying transcript text or analysis logic has changed.

             **Pre-conditions & Checks:**
             - Requires authentication via JWT (using asynchronous authentication).
             - Checks if the specified `transcript_id` exists.
             - Checks if the transcript has content (either `raw_text` or an associated `original_file`).
             - Checks if the transcript is already `COMPLETED`, `PROCESSING`, or `PENDING` with an active task ID.

             **Workflow:**
             1. Performs the pre-condition checks.
             2. If valid, queues the `process_transcript_analysis` Celery task.
             3. Updates the transcript's status to `PENDING` and saves the new Celery task ID.

             **On Success:** Returns `202 Accepted` with the transcript's updated status details (showing `PENDING` and the new task ID)
              conforming to `TranscriptStatusSchemaOut`. This indicates the request to start analysis was accepted; completion is asynchronous.
             **On Failure:**
                 - Returns `404 Not Found` if the transcript does not exist.
                 - Returns `400 Bad Request` if the transcript has no content to analyze (status will be set to `FAILED`).
                 - Returns `409 Conflict` if the analysis is already completed, processing, or pending.
                 - Returns `500 Internal Server Error` if task queueing or status updates fail unexpectedly.
             """
             )
async def generate_analysis(request, transcript_id: int):
    transcript = await get_transcript_for_analysis(transcript_id)
    if transcript is None:
        return 404, {"detail": f"Transcript with id {transcript_id} not found"}
    if transcript.processing_status == Transcript.ProcessingStatus.COMPLETED:
         return 409, {"detail": f"Analysis for transcript {transcript_id} has already been completed."}
    if transcript.processing_status == Transcript.ProcessingStatus.PROCESSING:
         return 409, {"detail": f"Analysis for transcript {transcript_id} is already in progress."}
    if transcript.processing_status == Transcript.ProcessingStatus.PENDING and transcript.async_task_id:
         return 409, {"detail": f"Analysis for transcript {transcript_id} is already pending (Task ID: {transcript.async_task_id})."}

    transcript_text = transcript.raw_text
    has_file = await sync_to_async(lambda: bool(transcript.original_file and transcript.original_file.name))()
    if not transcript_text and not has_file:
        logger.warning(f"Attempted to generate analysis for transcript {transcript_id} with no text or file.")
        await sync_to_async(Transcript.objects.filter(id=transcript.id).update)(processing_status=Transcript.ProcessingStatus.FAILED,
                                                                                processing_error="Cannot analyze: Transcript has no text content or associated file.",
                                                                                async_task_id=None)
        return 400, {"detail": f"Transcript {transcript_id} has no text content or file to analyze. Marked as failed."}

    try:
        logger.info(f"Queueing analysis task for transcript {transcript_id} via generate endpoint.")
        task = process_transcript_analysis.delay(transcript.id)
        updated_count = await sync_to_async(Transcript.objects.filter(id=transcript.id).update)(processing_status=Transcript.ProcessingStatus.PENDING,
            async_task_id=task.id, processing_error=None)

        if updated_count == 0:
             logger.error(f"Failed to update transcript {transcript_id} status after queueing task (maybe deleted?).")
             return 500, {"detail": "Failed to update transcript status after queueing analysis."}

        logger.info(f"Transcript {transcript_id} status set to PENDING, task ID: {task.id}")
        updated_transcript = await get_transcript_for_analysis(transcript_id)
        if updated_transcript is None:
             return 500, {"detail": "Failed to retrieve transcript status after update."}

        return 202, updated_transcript

    except Exception as e:
        logger.error(f"Error queueing analysis task for transcript {transcript_id}: {e}", exc_info=True)
        await sync_to_async(Transcript.objects.filter(id=transcript.id).update)(processing_status=Transcript.ProcessingStatus.FAILED,
             processing_error=f"Failed to queue analysis task: {str(e)}",)
        return 500, {"detail": f"An unexpected error occurred while queueing the analysis task: {str(e)}"}

# @router.post(
#     "/process/direct/",
#     response={202: TranscriptStatusSchemaOut, 400: ErrorDetail, 500: ErrorDetail},tags=["analysis", "async"],auth=AsyncJWTAuth())
# async def direct_process_transcript(request, payload: DirectProcessInput = Form(None), file: Optional[UploadedFile] = File(None)):
#     transcript_text: Optional[str] = None
#     file_content: Optional[bytes] = None
#     original_filename: Optional[str] = None
#     source_type: Optional[str] = None
#
#     if payload and payload.raw_text:
#         transcript_text = payload.raw_text
#         source_type = 'text'
#         logger.info("Processing direct submission with raw text payload.")
#     elif file:
#         try:
#             original_filename = file.name
#             file_content = await file.read()
#             source_type = 'file'
#             try:
#                 transcript_text_from_file = file_content.decode('utf-8')
#                 logger.info(f"Processing direct submission with file: {original_filename}. Decoded as UTF-8.")
#             except UnicodeDecodeError:
#                  logger.warning(f"Could not decode file {original_filename} as UTF-8. Analysis task must read from file.")
#                  transcript_text = ""
#             except Exception as decode_err:
#                  logger.error(f"Error decoding file {original_filename}: {decode_err}", exc_info=True)
#                  transcript_text = ""
#         except Exception as e:
#             logger.error(f"Error reading uploaded file '{file.name if file else 'N/A'}': {e}", exc_info=True)
#             return 400, {"detail": f"Could not read uploaded file: {e}"}
#     else:
#         logger.warning("Direct process endpoint called without raw_text payload or file upload.")
#         return 400, {"detail": "Please provide either 'raw_text' in the form data or upload a 'file'."}
#
#     if not (transcript_text and transcript_text.strip()) and not file_content:
#          logger.warning(f"Direct process submission provided empty content (Source: {source_type}). Text empty and no file content.")
#          return 400, {"detail": "Transcript content cannot be empty if no file is provided or the file is empty."}
#
#     transcript_instance = None
#     try:
#         @sync_to_async(thread_sensitive=True)
#         def create_meeting_and_transcript_sync():
#             nonlocal transcript_instance
#             with transaction.atomic():
#                 meeting = Meeting.objects.create(title=f"Meeting (Processing {datetime.now().strftime('%Y%m%d_%H%M%S')})",
#                     meeting_date=datetime.now().date(), participants=[])
#                 logger.info(f"Created placeholder Meeting ID: {meeting.id}")
#
#                 transcript_instance = Transcript(meeting=meeting,
#                     raw_text=transcript_text if source_type == 'text' and transcript_text and transcript_text.strip() else "",
#                     processing_status=Transcript.ProcessingStatus.PENDING,)
#                 if source_type == 'file' and file_content and original_filename:
#                     transcript_instance.original_file.save(original_filename,ContentFile(file_content),save=False )
#                     logger.info(f"Attached original file '{original_filename}' to transcript.")
#                     if not transcript_instance.raw_text:
#                          logger.info("Raw text field is empty for file upload, analysis task will read from file.")
#
#                 transcript_instance.save()
#                 logger.info(f"Created Transcript ID: {transcript_instance.id} for Meeting ID: {meeting.id}")
#                 return transcript_instance
#         transcript = await create_meeting_and_transcript_sync()
#         logger.info(f"Queueing analysis task for newly created transcript {transcript.id}")
#         task = process_transcript_analysis.delay(transcript.id)
#         transcript.async_task_id = task.id
#         await sync_to_async(transcript.save)(update_fields=['async_task_id'])
#         logger.info(f"Transcript {transcript.id} task ID set to {task.id}")
#
#         return 202, transcript
#
#     except Exception as e:
#         logger.error(f"Unexpected error during direct processing submission: {e}", exc_info=True)
#         if transcript_instance and transcript_instance.pk:
#             try:
#                 await sync_to_async(Transcript.objects.filter(id=transcript_instance.id).update)(
#                     processing_status=Transcript.ProcessingStatus.FAILED,
#                     processing_error=f"Failed during direct processing submission: {str(e)}",
#                     async_task_id=None)
#                 logger.warning(f"Marked Transcript {transcript_instance.id} as FAILED due to direct processing error.")
#             except Exception as update_err:
#                  logger.error(f"Failed to mark transcript {transcript_instance.id} as FAILED after direct processing error: {update_err}")
#         return 500, {"detail": f"An unexpected internal error occurred during submission: {str(e)}"}


@sync_to_async
def get_transcript_for_analysis(transcript_id: int) -> Optional[Transcript]:
     try:
         return Transcript.objects.select_related('meeting').get(id=transcript_id)
     except Transcript.DoesNotExist:
         logger.warning(f"Transcript {transcript_id} not found during fetch for analysis generation.")
         return None
     except Exception as e:
         logger.error(f"Unexpected error fetching transcript {transcript_id} for analysis generation: {e}", exc_info=True)
         return None