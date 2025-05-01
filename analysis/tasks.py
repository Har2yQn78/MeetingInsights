import logging
import json
from typing import Optional
from celery import shared_task, chain
from django.db import transaction
from django.utils import timezone
from django.core.files.base import ContentFile
from transcripts.models import Transcript
from meetings.models import Meeting
from .models import AnalysisResult

from .service import TranscriptAnalysisService
from chatbot.tasks import generate_embeddings_task

logger = logging.getLogger(__name__)
def _read_file_sync(file_field) -> Optional[str]:
    if not file_field or not file_field.name:
        logger.warning("Attempted to read from an empty or non-existent file field.")
        return None
    try:
        file_field.seek(0)
        with file_field.open('rb') as f:
            content_bytes = f.read()
        try:
            decoded_content = content_bytes.decode('utf-8')
            logger.debug(f"Successfully decoded file '{file_field.name}' as UTF-8.")
            return decoded_content
        except UnicodeDecodeError:
            logger.warning(f"Could not decode file '{file_field.name}' as UTF-8, trying latin-1.")
            try:
                decoded_content = content_bytes.decode('latin-1')
                logger.debug(f"Successfully decoded file '{file_field.name}' as latin-1 (fallback).")
                return decoded_content
            except Exception as decode_err_latin1:
                logger.error(f"Failed to decode file '{file_field.name}' even as latin-1: {decode_err_latin1}", exc_info=True)
                raise ValueError(f"Could not decode file {file_field.name} using UTF-8 or latin-1.")

    except FileNotFoundError:
         logger.error(f"File not found for {file_field.name} at path {file_field.path}", exc_info=True)
         raise
    except Exception as e:
        logger.error(f"Error reading file field '{file_field.name}': {e}", exc_info=True)
        raise IOError(f"Could not read file {file_field.name}: {e}") from e

@shared_task(bind=True, max_retries=3, default_retry_delay=60, autoretry_for=(IOError, ConnectionError, RuntimeError), retry_backoff=True, name='analysis.tasks.process_transcript_analysis')
def process_transcript_analysis(self, transcript_id: int):
    """
    Celery task to process a transcript for analysis (summary, key points, etc.):
    1. Fetches the transcript.
    2. Sets status to PROCESSING.
    3. Reads raw text (from field or file).
    4. Calls TranscriptAnalysisService to get analysis results.
    5. Saves the AnalysisResult.
    6. Updates transcript status (COMPLETED/FAILED) and title (if generated).
    7. On success, triggers the chatbot embedding generation task.
    """
    task_id = self.request.id
    logger.info(f"Celery Task [{task_id}]: Starting analysis for Transcript ID: {transcript_id}.")

    transcript: Optional[Transcript] = None
    try:
        with transaction.atomic():
            transcript = Transcript.objects.select_for_update().select_related('meeting').get(id=transcript_id)
            if transcript.processing_status == Transcript.ProcessingStatus.COMPLETED:
                 logger.warning(f"Task [{task_id}]: Analysis for Transcript {transcript_id} is already COMPLETED. Skipping.")
                 if transcript.embedding_status in [Transcript.EmbeddingStatus.NONE, Transcript.EmbeddingStatus.FAILED]:
                      logger.info(f"Task [{task_id}]: Analysis complete, but embedding status is {transcript.embedding_status}. Triggering embedding task.")
                      transcript.embedding_status = Transcript.EmbeddingStatus.PENDING
                      transcript.save(update_fields=['embedding_status'])
                      generate_embeddings_task.delay(transcript_id)
                 return {"status": "skipped", "reason": "Analysis already completed"}

            if transcript.processing_status == Transcript.ProcessingStatus.FAILED:
                 logger.warning(f"Task [{task_id}]: Analysis for Transcript {transcript_id} previously FAILED. Consider re-triggering manually if needed. Skipping.")
                 return {"status": "skipped", "reason": "Previously failed"}
            if transcript.processing_status == Transcript.ProcessingStatus.PROCESSING and task_id != transcript.async_task_id:
                 logger.warning(f"Task [{task_id}]: Analysis for Transcript {transcript_id} is already PROCESSING by task ({transcript.async_task_id}). Skipping.")
                 return {"status": "skipped", "reason": "Already processing by another task"}
            transcript.processing_status = Transcript.ProcessingStatus.PROCESSING
            transcript.processing_error = None
            transcript.async_task_id = task_id
            transcript.updated_at = timezone.now()
            transcript.save(update_fields=['processing_status', 'processing_error', 'async_task_id', 'updated_at'])
            logger.info(f"Task [{task_id}]: Transcript {transcript_id} processing_status set to PROCESSING.")

    except Transcript.DoesNotExist:
        logger.error(f"Task [{task_id}]: Transcript with id {transcript_id} not found. Cannot process analysis.")
        return {"status": "error", "reason": "Transcript not found"}
    except Exception as e:
        logger.error(f"Task [{task_id}]: Error fetching/updating transcript {transcript_id} before analysis: {e}", exc_info=True)
        return {"status": "error", "reason": f"Failed initial transcript setup: {e}"}

    transcript_text = transcript.raw_text
    file_read_error_occurred = False
    file_read_error_message = ""

    if not transcript_text and transcript.original_file and transcript.original_file.name:
        logger.info(f"Task [{task_id}]: Transcript {transcript_id} has no raw_text, reading file {transcript.original_file.name}")
        try:
            transcript_text = _read_file_sync(transcript.original_file)
            if transcript_text is None:
                logger.error(f"Task [{task_id}]: File read function unexpectedly returned None for tx {transcript_id}")
                file_read_error_message = "Failed to extract text content from file (read returned None)."
                file_read_error_occurred = True

        except (IOError, ValueError, FileNotFoundError) as e:
            logger.error(f"Task [{task_id}]: Failed reading/decoding file for transcript {transcript_id}: {e}", exc_info=True)
            file_read_error_message = f"Error reading/decoding transcript file: {str(e)}"
            file_read_error_occurred = True

    if file_read_error_occurred:
        try:
            with transaction.atomic():
                tx_fail = Transcript.objects.select_for_update().get(id=transcript_id)
                if tx_fail.processing_status == Transcript.ProcessingStatus.PROCESSING and tx_fail.async_task_id == task_id:
                    tx_fail.processing_status = Transcript.ProcessingStatus.FAILED
                    tx_fail.processing_error = file_read_error_message[:1024]
                    tx_fail.updated_at = timezone.now()
                    tx_fail.save(update_fields=['processing_status', 'processing_error', 'updated_at'])
                    logger.info(f"Task [{task_id}]: Marked Transcript {transcript_id} as FAILED (file read/decode error).")
                else:
                    logger.warning(f"Task [{task_id}]: Transcript {transcript_id} status was '{tx_fail.processing_status}' (Task ID: {tx_fail.async_task_id}) during file read failure. Status not changed by this task.")
        except Exception as update_err:
             logger.error(f"Task [{task_id}]: CRITICAL - Failed to update status after file read error: {update_err}", exc_info=True)
        return {"status": "error", "reason": f"File read/decode error: {file_read_error_message}"}

    if not transcript_text or not transcript_text.strip():
        logger.warning(f"Task [{task_id}]: Transcript {transcript_id} has empty content after checking field and file. Cannot analyze.")
        error_message = "Transcript content is empty."
        try:
            with transaction.atomic():
                 tx_fail = Transcript.objects.select_for_update().get(id=transcript_id)
                 if tx_fail.processing_status == Transcript.ProcessingStatus.PROCESSING and tx_fail.async_task_id == task_id:
                     tx_fail.processing_status = Transcript.ProcessingStatus.FAILED
                     tx_fail.processing_error = error_message
                     tx_fail.updated_at = timezone.now()
                     tx_fail.save(update_fields=['processing_status', 'processing_error', 'updated_at'])
                     logger.info(f"Task [{task_id}]: Marked Transcript {transcript_id} as FAILED (empty content).")
                 else:
                      logger.warning(f"Task [{task_id}]: Tx {transcript_id} status was '{tx_fail.processing_status}' (Task ID: {tx_fail.async_task_id}) during empty content check. Status not changed by this task.")
        except Exception as update_err:
             logger.error(f"Task [{task_id}]: CRITICAL - Failed update status for empty content: {update_err}", exc_info=True)
        return {"status": "error", "reason": "Empty content"}

    analysis_db_object = None
    try:
        logger.info(f"Task [{task_id}]: Instantiating analysis service for tx {transcript_id}...")
        llm_service = TranscriptAnalysisService()
        analysis_results = llm_service.analyze_transcript_sync(transcript_text)
        logger.info(f"Task [{task_id}]: LLM analysis completed for tx {transcript_id}.")

        with transaction.atomic():
            transcript_final = Transcript.objects.select_for_update().select_related('meeting').get(id=transcript_id)

            if not (transcript_final.processing_status == Transcript.ProcessingStatus.PROCESSING and transcript_final.async_task_id == task_id):
                logger.warning(f"Task [{task_id}]: Transcript {transcript_id} status changed to '{transcript_final.processing_status}' (Task ID: {transcript_final.async_task_id}) mid-analysis. Aborting result save.")
                return {"status": "aborted", "reason": f"Transcript status changed mid-task."}

            analysis_defaults = {
                'summary': analysis_results.get('summary'),
                'key_points': analysis_results.get('key_points') if isinstance(analysis_results.get('key_points'), list) else [],
                'task': analysis_results.get('task') or "",
                'responsible': analysis_results.get('responsible') or "",
                'deadline': analysis_results.get('deadline'),
                'updated_at': timezone.now(),
            }
            analysis_db_object, created = AnalysisResult.objects.update_or_create(
                transcript=transcript_final,
                defaults=analysis_defaults
            )
            action = "created" if created else "updated"
            logger.info(f"Task [{task_id}]: AnalysisResult {action} for tx {transcript_id} (PK: {analysis_db_object.pk}).")
            extracted_transcript_title = analysis_results.get('transcript_title')
            title_updated = False
            if extracted_transcript_title and transcript_final.title != extracted_transcript_title:
                transcript_final.title = extracted_transcript_title
                title_updated = True
                logger.info(f"Task [{task_id}]: Updating tx {transcript_id} title to '{extracted_transcript_title}'.")
            transcript_final.processing_status = Transcript.ProcessingStatus.COMPLETED
            transcript_final.processing_error = None
            transcript_final.updated_at = timezone.now()

            update_fields = ['processing_status', 'processing_error', 'updated_at']
            if title_updated:
                update_fields.append('title')
            transcript_final.embedding_status = Transcript.EmbeddingStatus.PENDING
            update_fields.append('embedding_status')
            transcript_final.save(update_fields=update_fields)
            logger.info(f"Task [{task_id}]: Transcript {transcript_id} processing_status set to COMPLETED and embedding_status to PENDING.")

            try:
                generate_embeddings_task.delay(transcript_id)
                logger.info(f"Task [{task_id}]: Embedding task successfully queued for Transcript {transcript_id}.")
            except Exception as queue_err:
                 logger.error(f"Task [{task_id}]: CRITICAL - Failed to queue embedding task for Tx {transcript_id} after successful analysis: {queue_err}", exc_info=True)

        return {
            "status": "success",
            "analysis_id": analysis_db_object.pk if analysis_db_object else None,
            "transcript_id": transcript_id,
            "embedding_task_queued": True
        }

    except Exception as e:
        logger.error(f"Task [{task_id}]: Error during LLM analysis or saving for tx {transcript_id}: {type(e).__name__} - {e}", exc_info=True)
        try:
            with transaction.atomic():
                tx_fail = Transcript.objects.select_for_update().get(id=transcript_id)
                if tx_fail.processing_status == Transcript.ProcessingStatus.PROCESSING and tx_fail.async_task_id == task_id:
                    tx_fail.processing_status = Transcript.ProcessingStatus.FAILED
                    error_message = f"Analysis failed: {type(e).__name__}: {str(e)}"
                    tx_fail.processing_error = error_message[:1024]
                    tx_fail.updated_at = timezone.now()
                    tx_fail.embedding_status = Transcript.EmbeddingStatus.NONE
                    tx_fail.save(update_fields=['processing_status', 'processing_error', 'updated_at', 'embedding_status'])
                    logger.info(f"Task [{task_id}]: Marked Transcript {transcript_id} as FAILED due to error: {type(e).__name__}")
                else:
                     logger.warning(f"Task [{task_id}]: Tx {transcript_id} status was '{tx_fail.processing_status}' (Task ID: {tx_fail.async_task_id}) when analysis failure occurred. Not marking FAILED by this task.")
        except Exception as update_err:
            logger.error(f"Task [{task_id}]: CRITICAL - Failed to update tx {transcript_id} status to FAILED after analysis error: {update_err}", exc_info=True)
        if isinstance(e, (ValueError, TypeError, json.JSONDecodeError)):
             logger.warning(f"Task [{task_id}]: Non-retryable error for tx {transcript_id}: {type(e).__name__}. No retry.")
             return {"status": "error", "reason": f"Non-retryable error: {str(e)}"}
        else:
             logger.warning(f"Task [{task_id}]: Potentially retryable error for tx {transcript_id}: {type(e).__name__}. Retrying...")
             raise self.retry(exc=e)