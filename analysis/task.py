import logging
from celery import shared_task
from django.core.files.base import ContentFile
from django.db import transaction

from transcripts.models import Transcript
from .models import AnalysisResult
from .service import TranscriptAnalysisService

logger = logging.getLogger(__name__)

def _read_file_sync(file_field):
    try:
        with file_field.open('r') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Error reading file field {file_field.name}: {e}", exc_info=True)
        raise

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_transcript_analysis(self, transcript_id: int):
    logger.info(f"Celery Task: Starting analysis for Transcript ID: {transcript_id}")
    try:
        with transaction.atomic():
            transcript = Transcript.objects.select_for_update().get(id=transcript_id)

            if transcript.processing_status in [Transcript.ProcessingStatus.COMPLETED, Transcript.ProcessingStatus.FAILED]:
                 logger.warning(f"Transcript {transcript_id} is already in state {transcript.processing_status}. Skipping analysis.")
                 return {"status": "skipped", "reason": f"Already {transcript.processing_status}"}

            transcript.processing_status = Transcript.ProcessingStatus.PROCESSING
            transcript.processing_error = None
            transcript.async_task_id = self.request.id
            transcript.save(update_fields=['processing_status', 'processing_error', 'async_task_id', 'updated_at'])
            logger.info(f"Transcript {transcript_id} status set to PROCESSING.")

    except Transcript.DoesNotExist:
        logger.error(f"Celery Task: Transcript with id {transcript_id} not found.")
        return {"status": "error", "reason": "Transcript not found"}
    except Exception as e:
        logger.error(f"Celery Task: Error fetching/updating transcript {transcript_id} before analysis: {e}", exc_info=True)
        raise self.retry(exc=e)

    transcript_text = transcript.raw_text
    if not transcript_text and transcript.original_file:
        logger.info(f"Reading transcript text from original file for transcript {transcript_id}")
        try:
            transcript_text = _read_file_sync(transcript.original_file)
        except Exception as e:
            logger.error(f"Failed reading file for transcript {transcript_id}: {e}", exc_info=True)
            transcript.processing_status = Transcript.ProcessingStatus.FAILED
            transcript.processing_error = f"Error reading transcript file: {str(e)}"
            transcript.save(update_fields=['processing_status', 'processing_error', 'updated_at'])
            return {"status": "error", "reason": "File read error"}

    if not transcript_text or not transcript_text.strip():
        logger.warning(f"Transcript {transcript_id} has empty content.")
        transcript.processing_status = Transcript.ProcessingStatus.FAILED
        transcript.processing_error = "Transcript content is empty."
        transcript.save(update_fields=['processing_status', 'processing_error', 'updated_at'])
        return {"status": "error", "reason": "Empty content"}

    try:
        logger.info(f"Instantiating TranscriptAnalysisService for transcript {transcript_id}...")
        llm_service = TranscriptAnalysisService()
        extracted_data = llm_service.analyze_transcript_sync(transcript_text)

        logger.info(f"LLM analysis completed for transcript {transcript_id}.")
        meeting_details = extracted_data["meeting_details"]
        analysis_results = extracted_data["analysis_results"]

        with transaction.atomic():
            defaults = {
                'summary': analysis_results.get('summary'),
                'key_points': analysis_results.get('key_points', []),
                'task': analysis_results.get('task', ''),
                'responsible': analysis_results.get('responsible', ''),
                'deadline': analysis_results.get('deadline'),
            }
            if defaults['key_points'] is None: defaults['key_points'] = []
            if defaults['task'] is None: defaults['task'] = ""
            if defaults['responsible'] is None: defaults['responsible'] = ""

            analysis_db_object, created = AnalysisResult.objects.update_or_create(
                transcript=transcript,
                defaults=defaults
            )
            logger.info(f"AnalysisResult {'created' if created else 'updated'} for transcript {transcript_id}.")

            transcript.processing_status = Transcript.ProcessingStatus.COMPLETED
            transcript.processing_error = None
            transcript.save(update_fields=['processing_status', 'processing_error', 'updated_at'])
            logger.info(f"Transcript {transcript_id} status set to COMPLETED.")

        return {"status": "success", "analysis_id": analysis_db_object.pk}

    except Exception as e:
        logger.error(f"Celery Task: Error during analysis or saving for transcript {transcript_id}: {e}", exc_info=True)
        try:
            with transaction.atomic():
                transcript_fail = Transcript.objects.select_for_update().get(id=transcript_id)
                transcript_fail.processing_status = Transcript.ProcessingStatus.FAILED
                error_message = f"Analysis failed: {type(e).__name__}: {str(e)}"
                transcript_fail.processing_error = error_message[:1024] # Truncate if necessary
                transcript_fail.save(update_fields=['processing_status', 'processing_error', 'updated_at'])
            logger.info(f"Transcript {transcript_id} status set to FAILED.")
        except Exception as update_err:
            logger.error(f"Celery Task: CRITICAL - Failed to update transcript {transcript_id} status to FAILED: {update_err}", exc_info=True)

        if isinstance(e, (ValueError, TypeError, Transcript.DoesNotExist)):
             return {"status": "error", "reason": f"Non-retryable error: {str(e)}"}
        else:
             raise self.retry(exc=e)