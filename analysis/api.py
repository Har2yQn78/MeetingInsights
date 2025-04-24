from typing import List, Optional
from django.shortcuts import get_object_or_404
from django.http import Http404 # Import Http404
from ninja import Router
from asgiref.sync import sync_to_async
import logging

from transcripts.models import Transcript
from .models import AnalysisResult
from .schemas import AnalysisResultSchemaOut, ErrorDetail
from .service import TranscriptAnalysisService

router = Router(tags=["analysis"])
logger = logging.getLogger(__name__)

@router.get("/transcript/{transcript_id}/", response={200: AnalysisResultSchemaOut, 404: ErrorDetail})
def get_transcript_analysis(request, transcript_id: int):
    try:
        analysis = get_object_or_404(
            AnalysisResult.objects.select_related('transcript'),
            transcript_id=transcript_id
        )
        return 200, analysis
    except AnalysisResult.DoesNotExist:
        if Transcript.objects.filter(id=transcript_id).exists():
             return 404, {"detail": f"Analysis for transcript {transcript_id} has not been generated yet."}
        else:
             return 404, {"detail": f"Transcript with id {transcript_id} not found."}
    except Exception as e:
        logger.error(f"Error getting analysis for transcript {transcript_id}: {e}", exc_info=True)
        return 500, {"detail": "An internal error occurred"}


@router.get("/meeting/{meeting_id}/", response=List[AnalysisResultSchemaOut])
def get_meeting_analysis(request, meeting_id: int):
    return AnalysisResult.objects.filter(transcript__meeting_id=meeting_id).order_by('-created_at')

@sync_to_async
def get_transcript_for_analysis(transcript_id: int) -> Optional[Transcript]:
    try:
        return Transcript.objects.get(id=transcript_id)
    except Transcript.DoesNotExist:
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching transcript {transcript_id}: {e}", exc_info=True)
        return None


@sync_to_async
def update_or_create_analysis(transcript: Transcript, analysis_data: dict):
    if not isinstance(analysis_data, dict):
        logger.error(f"Analysis data for transcript {transcript.id} is not a dict: {type(analysis_data)}")
        raise ValueError("Analysis service returned invalid data format.")
    action_items = analysis_data.get('action_items', {})
    if not isinstance(action_items, dict):
        action_items = {}
    try:
        analysis_result, created = AnalysisResult.objects.update_or_create(
            transcript=transcript,
            defaults={
                'summary': analysis_data.get('summary', ''),
                'key_points': analysis_data.get('key_points', []),
                'task': action_items.get('task', ''),
                'responsible': action_items.get('responsible', ''),
                'deadline': action_items.get('deadline', None),
            }
        )
        return analysis_result, created
    except Exception as e:
        logger.error(f"Error saving analysis for transcript {transcript.id}: {e}", exc_info=True)
        # Re-raise the exception to be caught by the main endpoint handler
        raise



@router.post("/generate/{transcript_id}/", response={200: AnalysisResultSchemaOut, 400: ErrorDetail, 404: ErrorDetail, 500: ErrorDetail})
async def generate_analysis(request, transcript_id: int):
    transcript = await get_transcript_for_analysis(transcript_id)
    if transcript is None:
        return 404, {"detail": f"Transcript with id {transcript_id} not found"}
    transcript_text = transcript.raw_text
    if not transcript_text or not transcript_text.strip():
        logger.warning(f"Attempted to analyze transcript {transcript_id} with empty raw_text.")
        return 400, {"detail": f"Transcript with id {transcript_id} has no raw text to analyze."}
    try:
        logger.info(f"Starting analysis for transcript {transcript_id}...")
        llm_service = TranscriptAnalysisService()
        analysis_result_data = await llm_service.analyze_transcript(transcript_text)
        analysis_db_object, created = await update_or_create_analysis(transcript, analysis_result_data)
        logger.info(f"Analysis for transcript {transcript_id} {'created' if created else 'updated'} successfully.")
        return 200, analysis_db_object

    except ValueError as ve:
         logger.error(f"Data format error during analysis saving for transcript {transcript_id}: {ve}", exc_info=True)
         return 500, {"detail": f"Internal error saving analysis: {str(ve)}"}
    except Exception as e:
        logger.error(f"Error generating or saving analysis for transcript {transcript_id}: {e}", exc_info=True)
        return 500, {"detail": f"An unexpected error occurred during analysis generation: {str(e)}"}
