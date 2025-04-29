import logging
import json
from celery import shared_task
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from datetime import datetime, date
from meetinginsight import settings
from transcripts.models import Transcript
from meetings.models import Meeting
from .models import AnalysisResult
from .service import TranscriptAnalysisService

logger = logging.getLogger(__name__)

def _read_file_sync(file_field):
    if not file_field or not file_field.name:
        logger.warning("Attempted to read from an empty or non-existent file field.")
        return None
    try:
        with file_field.open('rb') as f:
            content_bytes = f.read()

        try:
            decoded_content = content_bytes.decode('utf-8')
            logger.debug(f"Successfully decoded file {file_field.name} as UTF-8.")
            return decoded_content
        except UnicodeDecodeError:
            logger.warning(f"Could not decode file {file_field.name} as UTF-8, trying latin-1.")
            try:
                decoded_content = content_bytes.decode('latin-1')
                logger.debug(f"Successfully decoded file {file_field.name} as latin-1 (fallback).")
                return decoded_content
            except Exception as decode_err_latin1:
                logger.error(f"Failed to decode file {file_field.name} even as latin-1: {decode_err_latin1}", exc_info=True)
                raise ValueError(f"Could not decode file {file_field.name} using UTF-8 or latin-1.")

    except FileNotFoundError:
         logger.error(f"File not found for {file_field.name} at path {file_field.path}", exc_info=True)
         raise
    except Exception as e:
        logger.error(f"Error reading file field {file_field.name}: {e}", exc_info=True)
        raise IOError(f"Could not read file {file_field.name}: {e}") from e

@shared_task(bind=True, max_retries=3, default_retry_delay=60, autoretry_for=(IOError, ConnectionError, RuntimeError), retry_backoff=True)
def process_transcript_analysis(self, transcript_id: int):
    logger.info(f"Celery Task: Starting analysis for Transcript ID: {transcript_id}. Task ID: {self.request.id}")
    try:
        with transaction.atomic():
            transcript = Transcript.objects.select_for_update().select_related('meeting').get(id=transcript_id)

            # Keep status checks
            if transcript.processing_status == Transcript.ProcessingStatus.COMPLETED:
                 logger.warning(f"Task {self.request.id}: Transcript {transcript_id} is already COMPLETED. Skipping analysis.")
                 return {"status": "skipped", "reason": "Already completed"}
            if transcript.processing_status == Transcript.ProcessingStatus.FAILED:
                 logger.warning(f"Task {self.request.id}: Transcript {transcript_id} is already FAILED. Skipping analysis.")
                 return {"status": "skipped", "reason": "Already failed"}
            if transcript.processing_status == Transcript.ProcessingStatus.PROCESSING and self.request.id != transcript.async_task_id:
                 logger.warning(f"Task {self.request.id}: Transcript {transcript_id} is already PROCESSING by another task ({transcript.async_task_id}). Skipping.")
                 return {"status": "skipped", "reason": "Already processing by another task"}

            transcript.processing_status = Transcript.ProcessingStatus.PROCESSING
            transcript.processing_error = None
            transcript.async_task_id = self.request.id
            transcript.updated_at = timezone.now()
            transcript.save(update_fields=['processing_status', 'processing_error', 'async_task_id', 'updated_at'])
            logger.info(f"Task {self.request.id}: Transcript {transcript_id} status set to PROCESSING.")

    except Transcript.DoesNotExist:
        logger.error(f"Task {self.request.id}: Transcript with id {transcript_id} not found. Cannot process.")
        return {"status": "error", "reason": "Transcript not found"}
    except Exception as e:
        logger.error(f"Task {self.request.id}: Error fetching/updating transcript {transcript_id} before analysis: {e}", exc_info=True)
        raise self.retry(exc=e)

    transcript_text = transcript.raw_text
    if not transcript_text and transcript.original_file and transcript.original_file.name:
        logger.info(f"Task {self.request.id}: Transcript {transcript_id} has no raw_text, attempting to read from file {transcript.original_file.name}")
        try:
            transcript_text = _read_file_sync(transcript.original_file)
        except (IOError, ValueError, FileNotFoundError) as e:
            logger.error(f"Task {self.request.id}: Failed reading file for transcript {transcript_id}: {e}", exc_info=True)
            error_message = f"Error reading transcript file: {str(e)}"
            try:
                with transaction.atomic():
                    transcript_fail = Transcript.objects.select_for_update().get(id=transcript_id)
                    if transcript_fail.processing_status == Transcript.ProcessingStatus.PROCESSING:
                        transcript_fail.processing_status = Transcript.ProcessingStatus.FAILED
                        transcript_fail.processing_error = error_message[:1024]
                        transcript_fail.updated_at = timezone.now()
                        transcript_fail.save(update_fields=['processing_status', 'processing_error', 'updated_at'])
                        logger.info(f"Task {self.request.id}: Marked Transcript {transcript_id} as FAILED due to file read error.")
                    else:
                         logger.warning(f"Task {self.request.id}: Transcript {transcript_id} was not PROCESSING during file read failure. Status unchanged.")
            except Exception as update_err:
                 logger.error(f"Task {self.request.id}: CRITICAL - Failed to update transcript {transcript_id} status to FAILED after file read error: {update_err}", exc_info=True)
            return {"status": "error", "reason": "File read error"}

    if not transcript_text or not transcript_text.strip():
        logger.warning(f"Task {self.request.id}: Transcript {transcript_id} has empty content after checking text field and file. Cannot analyze.")
        error_message = "Transcript content is empty."
        try:
            with transaction.atomic():
                 transcript_fail = Transcript.objects.select_for_update().get(id=transcript_id)
                 if transcript_fail.processing_status == Transcript.ProcessingStatus.PROCESSING:
                     transcript_fail.processing_status = Transcript.ProcessingStatus.FAILED
                     transcript_fail.processing_error = error_message
                     transcript_fail.updated_at = timezone.now()
                     transcript_fail.save(update_fields=['processing_status', 'processing_error', 'updated_at'])
                     logger.info(f"Task {self.request.id}: Marked Transcript {transcript_id} as FAILED due to empty content.")
                 else:
                     logger.warning(f"Task {self.request.id}: Transcript {transcript_id} was not PROCESSING during empty content failure. Status unchanged.")
        except Exception as update_err:
             logger.error(f"Task {self.request.id}: CRITICAL - Failed to update transcript {transcript_id} status to FAILED for empty content: {update_err}", exc_info=True)
        return {"status": "error", "reason": "Empty content"}

    try:
        logger.info(f"Task {self.request.id}: Instantiating TranscriptAnalysisService for transcript {transcript_id}...")
        llm_service = TranscriptAnalysisService()
        analysis_results = llm_service.analyze_transcript_sync(transcript_text)
        logger.info(f"Task {self.request.id}: LLM analysis completed successfully for transcript {transcript_id}.")

        with transaction.atomic():
            transcript_final = Transcript.objects.select_for_update().select_related('meeting').get(id=transcript_id)
            if transcript_final.processing_status != Transcript.ProcessingStatus.PROCESSING:
                logger.warning(f"Task {self.request.id}: Transcript {transcript_id} status changed unexpectedly to {transcript_final.processing_status} before final save. Aborting final update.")
                return {"status": "aborted", "reason": f"Transcript status changed to {transcript_final.processing_status} mid-task."}

            analysis_defaults = {
                'summary': analysis_results.get('summary'),
                'key_points': analysis_results.get('key_points', []),
                'task': analysis_results.get('task', ''),
                'responsible': analysis_results.get('responsible', ''),
                'deadline': analysis_results.get('deadline'),
                'updated_at': timezone.now(),
            }
            if analysis_defaults['key_points'] is None: analysis_defaults['key_points'] = []
            if analysis_defaults['task'] is None: analysis_defaults['task'] = ""
            if analysis_defaults['responsible'] is None: analysis_defaults['responsible'] = ""
            analysis_db_object, created = AnalysisResult.objects.update_or_create(transcript=transcript_final, defaults=analysis_defaults)
            action = "created" if created else "updated"
            logger.info(f"Task {self.request.id}: AnalysisResult {action} for transcript {transcript_id} (ID: {analysis_db_object.pk}).")
            extracted_transcript_title = analysis_results.get('transcript_title')
            if extracted_transcript_title and transcript_final.title != extracted_transcript_title:
                transcript_final.title = extracted_transcript_title
                logger.info(f"Task {self.request.id}: Updating transcript {transcript_id} title to '{extracted_transcript_title}'.")
            elif not extracted_transcript_title and transcript_final.title:
                 pass

            transcript_final.processing_status = Transcript.ProcessingStatus.COMPLETED
            transcript_final.processing_error = None
            transcript_final.updated_at = timezone.now()
            transcript_final.save(update_fields=['processing_status', 'processing_error', 'updated_at', 'title'])
            logger.info(f"Task {self.request.id}: Transcript {transcript_id} status set to COMPLETED and title updated.")

        return {
            "status": "success",
            "analysis_id": analysis_db_object.pk,
            "transcript_id": transcript_id,
            "meeting_id": transcript_final.meeting_id,
            "meeting_updated": False
        }

    except Exception as e:
        logger.error(f"Task {self.request.id}: Error during analysis processing or saving for transcript {transcript_id}: {e}", exc_info=True)
        try:
            with transaction.atomic():
                transcript_fail = Transcript.objects.select_for_update().get(id=transcript_id)
                if transcript_fail.processing_status == Transcript.ProcessingStatus.PROCESSING:
                    transcript_fail.processing_status = Transcript.ProcessingStatus.FAILED
                    error_message = f"Analysis failed: {type(e).__name__}: {str(e)}"
                    transcript_fail.processing_error = error_message[:1024]
                    transcript_fail.updated_at = timezone.now()
                    transcript_fail.save(update_fields=['processing_status', 'processing_error', 'updated_at'])
                    logger.info(f"Task {self.request.id}: Marked Transcript {transcript_id} as FAILED due to error: {type(e).__name__}")
                else:
                     logger.warning(f"Task {self.request.id}: Transcript {transcript_id} was not in PROCESSING state ({transcript_fail.processing_status}) when analysis failure occurred. Status not changed to FAILED.")
        except Exception as update_err:
            logger.error(f"Task {self.request.id}: CRITICAL - Failed to update transcript {transcript_id} status to FAILED after analysis error: {update_err}", exc_info=True)

        if isinstance(e, (ValueError, TypeError, json.JSONDecodeError)):
             logger.warning(f"Task {self.request.id}: Non-retryable error encountered for transcript {transcript_id}: {type(e).__name__}. No retry.")
             return {"status": "error", "reason": f"Non-retryable error: {str(e)}"}
        else:
             logger.warning(f"Task {self.request.id}: Retryable error encountered for transcript {transcript_id}: {type(e).__name__}. Retrying...")
             raise self.retry(exc=e)