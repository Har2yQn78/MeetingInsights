import logging
from typing import Optional
from celery import shared_task
from django.db import transaction
from django.utils import timezone
from django.conf import settings
import time
from transcripts.models import Transcript
from .models import TextChunk, MISTRAL_EMBEDDING_DIM
from .services import MistralService
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import TextNode
from llama_index.vector_stores.postgres import PGVectorStore

logger = logging.getLogger(__name__)

CHUNK_SIZE = 512
CHUNK_OVERLAP = 50
def get_vector_store() -> PGVectorStore:
    db_settings = settings.DATABASES['default']
    db_name = db_settings.get('NAME')
    db_host = db_settings.get('HOST')
    db_password = db_settings.get('PASSWORD')
    db_port_str = db_settings.get('PORT', '5432')
    db_user = db_settings.get('USER')
    if not all([db_name, db_host, db_user]):
        logger.error("Missing required database connection parameters (NAME, HOST, USER) in Django settings.")
        raise ValueError("Incomplete database configuration in settings.")
    try:
        db_port = int(db_port_str) if db_port_str else 5432
    except (ValueError, TypeError):
        logger.warning(f"Invalid database port configured ('{db_port_str}'). Defaulting to 5432.")
        db_port = 5432
    logger.debug(f"Connecting to PGVectorStore: User={db_user}, Host={db_host}, Port={db_port}, DB={db_name}")
    conn_string = f"postgresql+psycopg2://{db_settings.get('USER')}:{db_settings.get('PASSWORD')}@{db_settings.get('HOST')}:{db_settings.get('PORT')}/{db_settings.get('NAME')}"
    ssl_mode = db_settings.get('OPTIONS', {}).get('sslmode', 'require')
    conn_string += f"?sslmode={ssl_mode}"
    logger.debug(f"Connecting to PGVectorStore. Connection string inferred: postgresql+psycopg2://{db_settings.get('USER')}:***@{db_settings.get('HOST')}:{db_settings.get('PORT')}/{db_settings.get('NAME')}?sslmode={ssl_mode}")
    try:
        return PGVectorStore.from_params(
            database=db_name,
            host=db_host,
            password=db_password,
            port=db_port,
            user=db_user,
            table_name="chatbot_textchunk",
            embed_dim=MISTRAL_EMBEDDING_DIM
        )
    except Exception as e:
        logger.error(f"Failed to initialize PGVectorStore: {e}", exc_info=True)
        raise


@shared_task(bind=True, max_retries=2, default_retry_delay=90, autoretry_for=(ConnectionError,), name='chatbot.tasks.generate_embeddings_task')
def generate_embeddings_task(self, transcript_id: int):

    task_id = self.request.id
    logger.info(f"Task [{task_id}]: Starting embedding generation for Transcript ID: {transcript_id}.")

    transcript: Optional[Transcript] = None
    try:
        with transaction.atomic():
            transcript = Transcript.objects.select_for_update().get(id=transcript_id)
            if transcript.embedding_status == Transcript.EmbeddingStatus.COMPLETED:
                logger.warning(f"Task [{task_id}]: Embeddings for Transcript {transcript_id} are already COMPLETED. Skipping.")
                return {"status": "skipped", "reason": "Already completed"}
            if transcript.embedding_status == Transcript.EmbeddingStatus.PROCESSING:
                logger.warning(f"Task [{task_id}]: Embeddings for Transcript {transcript_id} are already PROCESSING. Skipping (potential duplicate task?).")
                return {"status": "skipped", "reason": "Already processing"}
            if transcript.processing_status != Transcript.ProcessingStatus.COMPLETED:
                 logger.error(f"Task [{task_id}]: Cannot generate embeddings for Transcript {transcript_id}. Main analysis status is '{transcript.processing_status}'. Requires 'COMPLETED'.")
                 return {"status": "failed", "reason": "Main analysis not completed"}

            transcript.embedding_status = Transcript.EmbeddingStatus.PROCESSING
            transcript.updated_at = timezone.now()
            transcript.save(update_fields=['embedding_status', 'updated_at'])
            logger.info(f"Task [{task_id}]: Transcript {transcript_id} embedding_status set to PROCESSING.")

    except Transcript.DoesNotExist:
        logger.error(f"Task [{task_id}]: Transcript with id {transcript_id} not found. Cannot process embeddings.")
        return {"status": "error", "reason": "Transcript not found"}
    except Exception as e:
        logger.error(f"Task [{task_id}]: Error fetching/updating transcript {transcript_id} before embedding: {e}", exc_info=True)
        return {"status": "error", "reason": f"Failed to prepare transcript: {e}"}

    all_nodes = []
    try:
        raw_text = transcript.raw_text
        if not raw_text or not raw_text.strip():
            if transcript.original_file and transcript.original_file.name:
                 logger.warning(f"Task [{task_id}]: Transcript {transcript_id} raw_text is empty, attempting to read file '{transcript.original_file.name}' again.")
                 raise ValueError("Transcript text content is empty even after checking file.")
            else:
                 raise ValueError("Transcript text content is empty and no original file found.")

        logger.info(f"Task [{task_id}]: Splitting text for Transcript {transcript_id} (length: {len(raw_text)} chars).")
        splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
        text_chunks = splitter.split_text(raw_text)
        logger.info(f"Task [{task_id}]: Split into {len(text_chunks)} chunks.")

        if not text_chunks:
             logger.warning(f"Task [{task_id}]: Text splitting resulted in zero chunks for Transcript {transcript_id}.")
             with transaction.atomic():
                 transcript_final = Transcript.objects.select_for_update().get(id=transcript_id)
                 transcript_final.embedding_status = Transcript.EmbeddingStatus.COMPLETED
                 transcript_final.updated_at = timezone.now()
                 transcript_final.save(update_fields=['embedding_status', 'updated_at'])
             return {"status": "success", "reason": "No text chunks to embed"}
        logger.info(f"Task [{task_id}]: Requesting embeddings for {len(text_chunks)} chunks...")
        mistral_service = MistralService()
        embeddings = mistral_service.get_embeddings(text_chunks)
        logger.info(f"Task [{task_id}]: Received {len(embeddings)} embeddings.")

        if len(embeddings) != len(text_chunks):
             raise ValueError(f"Mismatch embedding count: {len(embeddings)} vs chunk count: {len(text_chunks)}")

        logger.info(f"Task [{task_id}]: Creating LlamaIndex TextNodes...")
        all_nodes = []
        for i, chunk in enumerate(text_chunks):
            node = TextNode(
                text=chunk,
                embedding=embeddings[i].tolist(),
                metadata={
                    "transcript_id": transcript.id,
                    "meeting_id": transcript.meeting_id,
                }
            )
            all_nodes.append(node)
        logger.info(f"Task [{task_id}]: Created {len(all_nodes)} TextNodes.")

    except Exception as processing_err:
        logger.error(f"Task [{task_id}]: Error during text processing/embedding for Tx {transcript_id}: {processing_err}", exc_info=True)
        # Mark transcript as FAILED
        try:
            with transaction.atomic():
                tx_fail = Transcript.objects.select_for_update().get(id=transcript_id)
                if tx_fail.embedding_status == Transcript.EmbeddingStatus.PROCESSING:
                    tx_fail.embedding_status = Transcript.EmbeddingStatus.FAILED
                    tx_fail.updated_at = timezone.now()
                    tx_fail.save(update_fields=['embedding_status', 'updated_at'])
                    logger.info(f"Task [{task_id}]: Marked Transcript {transcript_id} embedding_status as FAILED.")
                else:
                     logger.warning(f"Task [{task_id}]: Tx {transcript_id} embedding status was {tx_fail.embedding_status} during processing failure. Status not changed to FAILED.")
        except Exception as update_err:
             logger.error(f"Task [{task_id}]: CRITICAL - Failed update status after processing error: {update_err}", exc_info=True)
        if isinstance(processing_err, ConnectionError):
             raise self.retry(exc=processing_err)
        return {"status": "error", "reason": f"Processing/Embedding failed: {processing_err}"}

    if not all_nodes:
         logger.warning(f"Task [{task_id}]: No nodes created for Tx {transcript_id}. Marking as complete.")
         if transcript.embedding_status == Transcript.EmbeddingStatus.PROCESSING:
              with transaction.atomic():
                  transcript_final = Transcript.objects.select_for_update().get(id=transcript_id)
                  transcript_final.embedding_status = Transcript.EmbeddingStatus.COMPLETED
                  transcript_final.updated_at = timezone.now()
                  transcript_final.save(update_fields=['embedding_status', 'updated_at'])
              return {"status": "success", "reason": "No nodes to store."}
         else:
              logger.error(f"Task [{task_id}]: Inconsistent state - no nodes but status is {transcript.embedding_status}")
              return {"status": "error", "reason": "Inconsistent state - no nodes but status not PROCESSING"}

    try:
        logger.info(f"Task [{task_id}]: Connecting to vector store...")
        vector_store = get_vector_store()

        logger.info(f"Task [{task_id}]: Adding {len(all_nodes)} nodes to vector store for Tx {transcript_id}...")
        vector_store.add(all_nodes)
        logger.info(f"Task [{task_id}]: Successfully added nodes to vector store.")

        with transaction.atomic():
            transcript_final = Transcript.objects.select_for_update().get(id=transcript_id)
            if transcript_final.embedding_status == Transcript.EmbeddingStatus.PROCESSING:
                transcript_final.embedding_status = Transcript.EmbeddingStatus.COMPLETED
                transcript_final.updated_at = timezone.now()
                transcript_final.save(update_fields=['embedding_status', 'updated_at'])
                logger.info(f"Task [{task_id}]: Marked Transcript {transcript_id} embedding_status as COMPLETED.")
            else:
                 logger.warning(f"Task [{task_id}]: Transcript {transcript_id} embedding status changed to '{transcript_final.embedding_status}' during vector store add. Final status not updated.")
                 return {"status": "warning", "reason": "Status changed during vector store add"}

        return {"status": "success", "transcript_id": transcript_id, "chunks_added": len(all_nodes)}

    except Exception as store_err:
        logger.error(f"Task [{task_id}]: Error storing embeddings in vector store for Tx {transcript_id}: {store_err}", exc_info=True)
        try:
            with transaction.atomic():
                tx_fail = Transcript.objects.select_for_update().get(id=transcript_id)
                if tx_fail.embedding_status == Transcript.EmbeddingStatus.PROCESSING:
                    tx_fail.embedding_status = Transcript.EmbeddingStatus.FAILED
                    tx_fail.updated_at = timezone.now()
                    tx_fail.save(update_fields=['embedding_status', 'updated_at'])
                    logger.info(f"Task [{task_id}]: Marked Transcript {transcript_id} embedding_status as FAILED due to storage error.")
                else:
                     logger.warning(f"Task [{task_id}]: Tx {transcript_id} embedding status was {tx_fail.embedding_status} during storage failure. Status not changed to FAILED.")
        except Exception as update_err:
             logger.error(f"Task [{task_id}]: CRITICAL - Failed update status after storage error: {update_err}", exc_info=True)
        if isinstance(store_err, ConnectionError):
            raise self.retry(exc=store_err)
        return {"status": "error", "reason": f"Vector store failed: {store_err}"}