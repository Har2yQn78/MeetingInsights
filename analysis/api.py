from typing import List, Optional
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja_jwt.authentication import JWTAuth

from transcripts.models import Transcript
from .models import AnalysisResult
from .schemas import AnalysisResultSchemaOut, ErrorDetail

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