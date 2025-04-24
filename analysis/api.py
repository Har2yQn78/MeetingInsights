from typing import List, Optional
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja_jwt.authentication import JWTAuth
from asgiref.sync import sync_to_async

from transcripts.models import Transcript
from .models import AnalysisResult
from .schemas import AnalysisResultSchemaOut, ErrorDetail
from .service import TranscriptAnalysisService

router = Router(tags=["analysis"])


@router.get("/transcript/{transcript_id}/", response={200: AnalysisResultSchemaOut, 404: ErrorDetail}, auth=JWTAuth())
def get_transcript_analysis(request, transcript_id: int):
    try:
        transcript = get_object_or_404(Transcript, id=transcript_id)
        analysis = get_object_or_404(AnalysisResult, transcript=transcript)
        return 200, analysis
    except (Transcript.DoesNotExist, AnalysisResult.DoesNotExist):
        return 404, {"detail": f"Analysis for transcript with id {transcript_id} not found"}


@router.get("/meeting/{meeting_id}/", response=List[AnalysisResultSchemaOut], auth=JWTAuth())
def get_meeting_analysis(request, meeting_id: int):
    return AnalysisResult.objects.filter(transcript__meeting_id=meeting_id).order_by('-created_at')


# Helper functions for async operations
@sync_to_async
def get_transcript(transcript_id):
    return get_object_or_404(Transcript, id=transcript_id)


@sync_to_async
def check_transcript_status(transcript):
    return transcript.processing_status == Transcript.ProcessingStatus.COMPLETED


@sync_to_async
def update_or_create_analysis(transcript, analysis_data):
    return AnalysisResult.objects.update_or_create(
        transcript=transcript,
        defaults={
            'summary': analysis_data.get('summary', ''),
            'key_points': analysis_data.get('key_points', []),
            'task': analysis_data.get('action_items', {}).get('task', ''),
            'responsible': analysis_data.get('action_items', {}).get('responsible', ''),
            'deadline': analysis_data.get('action_items', {}).get('deadline', None),
        }
    )


@router.post("/generate/{transcript_id}/", response={200: AnalysisResultSchemaOut, 404: ErrorDetail}, auth=JWTAuth())
async def generate_analysis(request, transcript_id: int):
    try:
        # Get transcript using sync_to_async
        transcript = await get_transcript(transcript_id)

        # Check if the transcript is completed
        is_completed = await check_transcript_status(transcript)
        if not is_completed:
            return 404, {"detail": f"Transcript with id {transcript_id} is not completed yet"}

        # Get the transcript text
        transcript_text = transcript.raw_text

        # Create the service and analyze
        llm_service = TranscriptAnalysisService()
        analysis_result = await llm_service.analyze_transcript(transcript_text)

        # Update or create the analysis result using sync_to_async
        analysis, created = await update_or_create_analysis(transcript, analysis_result)

        return 200, analysis

    except Exception as e:
        return 404, {"detail": f"Error generating analysis: {str(e)}"}