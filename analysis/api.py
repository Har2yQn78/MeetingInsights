from typing import List, Optional
from django.shortcuts import get_object_or_404
from django.http import Http404
from django.db import transaction
from django.core.files.base import ContentFile
from ninja import Router, File, UploadedFile, Form, Schema
from asgiref.sync import sync_to_async
import logging

from transcripts.models import Transcript
from meetings.models import Meeting
from .models import AnalysisResult
from .schemas import AnalysisResultSchemaOut, ErrorDetail
from .service import TranscriptAnalysisService

router = Router(tags=["analysis"])
logger = logging.getLogger(__name__)

@router.get("/transcript/{transcript_id}/", response={200: AnalysisResultSchemaOut, 404: ErrorDetail})
async def get_transcript_analysis(request, transcript_id: int):
    try:
        analysis = await sync_to_async(get_object_or_404)(
            AnalysisResult.objects.select_related('transcript', 'transcript__meeting'),
            transcript_id=transcript_id
        )
        return 200, analysis
    except AnalysisResult.DoesNotExist:
        transcript_exists = await sync_to_async(Transcript.objects.filter(id=transcript_id).exists)()
        if transcript_exists:
             return 404, {"detail": f"Analysis for transcript {transcript_id} has not been generated yet."}
        else:
             return 404, {"detail": f"Transcript with id {transcript_id} not found."}
    except Http404:
         return 404, {"detail": f"Transcript or Analysis with id {transcript_id} not found."}
    except Exception as e:
        logger.error(f"Error getting analysis for transcript {transcript_id}: {e}", exc_info=True)
        return 500, {"detail": "An internal server error occurred"}


@router.get("/meeting/{meeting_id}/", response=List[AnalysisResultSchemaOut])
async def get_meeting_analysis(request, meeting_id: int):
    results = await sync_to_async(list)(AnalysisResult.objects.filter( transcript__meeting_id=meeting_id).
                                        select_related('transcript', 'transcript__meeting').order_by('-created_at'))
    return results


@sync_to_async
def get_transcript_for_analysis(transcript_id: int) -> Optional[Transcript]:
    try:
        return Transcript.objects.select_related('meeting').get(id=transcript_id)
    except Transcript.DoesNotExist:
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching transcript {transcript_id}: {e}", exc_info=True)
        return None

@sync_to_async
def update_or_create_analysis(transcript: Transcript, analysis_data: dict):
    if not isinstance(analysis_data, dict):
        logger.error(f"Analysis data for transcript {transcript.id} is not a dict: {type(analysis_data)}")
        raise TypeError("Analysis service returned invalid data format (expected dict).")

    expected_keys = {'summary', 'key_points', 'task', 'responsible', 'deadline'}
    if not expected_keys.issubset(analysis_data.keys()):
         logger.warning(f"Analysis data missing expected keys for transcript {transcript.id}. Keys: {analysis_data.keys()}")

    try:
        defaults = {
            'summary': analysis_data.get('summary'),
            'key_points': analysis_data.get('key_points', []),
            'task': analysis_data.get('task', ''),
            'responsible': analysis_data.get('responsible', ''),
            'deadline': analysis_data.get('deadline'),
        }
        if defaults['key_points'] is None: defaults['key_points'] = []
        if defaults['task'] is None: defaults['task'] = ""
        if defaults['responsible'] is None: defaults['responsible'] = ""

        analysis_result, created = AnalysisResult.objects.update_or_create(
            transcript=transcript,
            defaults=defaults
        )
        return analysis_result, created
    except Exception as e:
        logger.error(f"Error saving analysis result for transcript {transcript.id}: {e}", exc_info=True)
        raise


@router.post("/generate/{transcript_id}/", response={200: AnalysisResultSchemaOut, 400: ErrorDetail, 404: ErrorDetail, 500: ErrorDetail})
async def generate_analysis(request, transcript_id: int):
    transcript = await get_transcript_for_analysis(transcript_id)
    if transcript is None:
        return 404, {"detail": f"Transcript with id {transcript_id} not found"}

    transcript_text = transcript.raw_text
    if not transcript_text and transcript.original_file:
        logger.info(f"Reading transcript text from original file for transcript {transcript_id}")
        try:
            def read_file_sync(file_field):
                with file_field.open('r') as f:
                    return f.read()
            transcript_text = await sync_to_async(read_file_sync)(transcript.original_file)
        except Exception as e:
            logger.error(f"Error reading original file for transcript {transcript_id}: {e}", exc_info=True)
            return 500, {"detail": "Could not read transcript file content."}

    if not transcript_text or not transcript_text.strip():
        logger.warning(f"Attempted to analyze transcript {transcript_id} with empty text/file content.")
        return 400, {"detail": f"Transcript {transcript_id} has no text content to analyze."}

    try:
        logger.info(f"Starting analysis generation task for transcript {transcript_id}...")
        llm_service = TranscriptAnalysisService()
        analysis_data_full = await llm_service.analyze_transcript(transcript_text)
        analysis_result_data = analysis_data_full["analysis_results"]
        analysis_db_object, created = await update_or_create_analysis(transcript, analysis_result_data)
        if transcript.processing_status != Transcript.ProcessingStatus.COMPLETED:
            await sync_to_async(Transcript.objects.filter(id=transcript_id).update)(
                 processing_status=Transcript.ProcessingStatus.COMPLETED,
                 processing_error=None
            )
            logger.info(f"Updated transcript {transcript_id} status to COMPLETED.")

        logger.info(f"Analysis for transcript {transcript_id} {'created' if created else 'updated'} successfully via generate endpoint.")
        return 200, analysis_db_object

    except (ValueError, TypeError) as ve:
         logger.error(f"Data format/type error during analysis generation/saving for transcript {transcript_id}: {ve}", exc_info=True)
         await sync_to_async(Transcript.objects.filter(id=transcript_id).update)(
             processing_status=Transcript.ProcessingStatus.FAILED,
             processing_error=f"Data processing error: {str(ve)}"
         )
         return 500, {"detail": f"Internal error processing analysis data: {str(ve)}"}
    except RuntimeError as rte:
         logger.error(f"Runtime error during analysis service for transcript {transcript_id}: {rte}", exc_info=True)
         await sync_to_async(Transcript.objects.filter(id=transcript_id).update)(
             processing_status=Transcript.ProcessingStatus.FAILED,
             processing_error=f"Analysis service error: {str(rte)}"
         )
         return 500, {"detail": f"Error during analysis service execution: {str(rte)}"}
    except Exception as e:
        logger.error(f"Error generating or saving analysis for transcript {transcript_id}: {e}", exc_info=True)
        await sync_to_async(Transcript.objects.filter(id=transcript_id).update)(
             processing_status=Transcript.ProcessingStatus.FAILED,
             processing_error=f"Unexpected error: {str(e)}"
         )
        return 500, {"detail": f"An unexpected error occurred during analysis generation: {str(e)}"}

def _create_meeting_transcript_analysis_sync(meeting_details: dict, analysis_results: dict, transcript_text: str,
                                             source_type: str, original_filename: Optional[str] = None,
                                             file_content: Optional[bytes] = None) -> AnalysisResult:
    with transaction.atomic():
        meeting = Meeting.objects.create(
            title=meeting_details["title"],
            meeting_date=meeting_details["meeting_date"],
            participants=meeting_details["participants"]
        )
        logger.info(f"SYNC: Created Meeting ID: {meeting.id} within transaction.")
        transcript_data = {
            'meeting': meeting,
            'raw_text': transcript_text,
            'processing_status': Transcript.ProcessingStatus.COMPLETED,
            'processing_error': None,
        }
        transcript = Transcript(**transcript_data)
        if source_type == 'file' and file_content and original_filename:
             transcript.original_file.save(
                 original_filename,
                 ContentFile(file_content),
                 save=False
             )
             logger.info(f"SYNC: Attached original file '{original_filename}' to transcript.")
        transcript.save()
        logger.info(f"SYNC: Created Transcript ID: {transcript.id} for Meeting ID: {meeting.id} within transaction.")
        analysis_defaults = {
            'summary': analysis_results.get('summary'),
            'key_points': analysis_results.get('key_points', []),
            'task': analysis_results.get('task', ''),
            'responsible': analysis_results.get('responsible', ''),
            'deadline': analysis_results.get('deadline'),
        }
        if analysis_defaults['key_points'] is None: analysis_defaults['key_points'] = []
        if analysis_defaults['task'] is None: analysis_defaults['task'] = ""
        if analysis_defaults['responsible'] is None: analysis_defaults['responsible'] = ""
        analysis_db_object, created = AnalysisResult.objects.update_or_create(
            transcript=transcript,
            defaults=analysis_defaults
        )
        if not created:
            logger.warning(f"SYNC: AnalysisResult for new transcript {transcript.id} was updated instead of created (unexpected).")

        logger.info(f"SYNC: AnalysisResult for transcript {transcript.id} created within transaction.")
        return analysis_db_object

class DirectProcessInput(Schema):
    raw_text: Optional[str] = None

@router.post(
    "/process/direct/",
    response={200: AnalysisResultSchemaOut, 400: ErrorDetail, 500: ErrorDetail},
    summary="Directly process transcript text or file, create meeting/transcript, analyze, and return analysis.",
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
            transcript_text = file_content.decode('utf-8', errors='replace')
            source_type = 'file'
            logger.info(f"Processing direct submission with file: {original_filename}")
        except Exception as e:
            logger.error(f"Error reading uploaded file '{file.name if file else 'N/A'}': {e}", exc_info=True)
            return 400, {"detail": f"Could not read or decode uploaded file: {e}"}
    else:
        logger.warning("Direct process endpoint called without raw_text or file.")
        return 400, {"detail": "Please provide either 'raw_text' in the form data or upload a 'file'."}

    if not transcript_text or not transcript_text.strip():
        logger.warning(f"Direct process submission provided empty content (source: {source_type}).")
        return 400, {"detail": "Transcript content cannot be empty."}


    try:
        llm_service = TranscriptAnalysisService()
        logger.info("Calling LLM service for direct analysis...")
        extracted_data = await llm_service.analyze_transcript(transcript_text)
        logger.info("LLM service call completed.")
        meeting_details = extracted_data["meeting_details"]
        analysis_results = extracted_data["analysis_results"]
        logger.info("Executing database operations within transaction...")
        final_analysis_object = await sync_to_async(
            _create_meeting_transcript_analysis_sync,
            thread_sensitive=True
        )(
            meeting_details=meeting_details,
            analysis_results=analysis_results,
            transcript_text=transcript_text,
            source_type=source_type,
            original_filename=original_filename,
            file_content=file_content
        )
        logger.info(f"Database operations complete. Final Analysis Object ID: {final_analysis_object.pk if final_analysis_object else 'N/A'}") # Use pk
        if final_analysis_object is None:
             logger.error("Database operations failed to return the analysis object.")
             return 500, {"detail": "Failed to save analysis results after processing."}


        logger.info(f"Direct processing successful. Returning analysis for Transcript ID: {final_analysis_object.transcript_id}")
        return 200, final_analysis_object

    except (ValueError, TypeError) as ve:
         logger.error(f"Data format or value error during direct processing: {ve}", exc_info=True)
         return 500, {"detail": f"Error processing transcript data: {str(ve)}"}
    except RuntimeError as rte:
         logger.error(f"Runtime error during direct processing (likely LLM issue): {rte}", exc_info=True)
         return 500, {"detail": f"Error during analysis service execution: {str(rte)}"}
    except Exception as e:
        logger.error(f"Unexpected error during direct processing: {e}", exc_info=True)
        return 500, {"detail": f"An unexpected internal error occurred: {str(e)}"}