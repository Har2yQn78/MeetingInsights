from celery import shared_task
from transcripts.models import Transcript
from .models import AnalysisResult
from .service import TranscriptAnalysisService
import asyncio
import traceback


@shared_task
def generate_analysis_task(transcript_id):
    try:
        transcript = Transcript.objects.get(id=transcript_id)
        if transcript.processing_status != Transcript.ProcessingStatus.COMPLETED:
            return
        transcript_text = transcript.raw_text
        LLM_service = TranscriptAnalysisService()

        analysis_result = asyncio.run(LLM_service.analyze_transcript(transcript_text))
        analysis, created = AnalysisResult.objects.update_or_create(
            transcript=transcript,
            defaults={
                'summary': analysis_result.get('summary', ''),
                'key_points': analysis_result.get('key_points', []),
                'action_items': analysis_result.get('action_items', [])
            }
        )

        return f"Analysis completed for transcript {transcript_id}"

    except Exception as e:
        print(f"Error generating analysis for transcript {transcript_id}: {e}")
        traceback.print_exc()
        raise