import logging
from typing import List, Optional

from ninja import Router
from ninja_jwt.authentication import JWTAuth
from django.shortcuts import get_object_or_404
from django.http import Http404
from asgiref.sync import sync_to_async

from llama_index.core.vector_stores import (
    VectorStoreQuery,
    MetadataFilters,
    MetadataFilter,
    FilterOperator,
)
from llama_index.vector_stores.postgres import PGVectorStore
from llama_index.core.schema import NodeWithScore

from transcripts.models import Transcript
from .schemas import EmbeddingStatusOut, QuestionIn, AnswerOut, ErrorDetail, EmbeddingStatusEnum
from .services import MistralService
from .tasks import get_vector_store
from .auth import AsyncJWTAuth

logger = logging.getLogger(__name__)
router = Router(tags=["chatbot"])

@router.get(
    "/status/{transcript_id}/",response={
        200: EmbeddingStatusOut,
        404: ErrorDetail,
        500: ErrorDetail,
    }, auth=JWTAuth(),
    summary="Get Embedding Status",
    description="Check the status of the vector embedding generation for a specific transcript."
)
def get_embedding_status(request, transcript_id: int):
    try:
        transcript = get_object_or_404(
            Transcript.objects.only('id', 'embedding_status', 'updated_at'),
            id=transcript_id
        )
        status_data = EmbeddingStatusOut(transcript_id=transcript.id, embedding_status=transcript.embedding_status, updated_at=transcript.updated_at
        )
        return 200, status_data

    except Http404:
        return 404, {"detail": f"Transcript with id {transcript_id} not found."}
    except Exception as e:
        logger.error(f"Error fetching embedding status for tx {transcript_id}: {e}", exc_info=True)
        return 500, {"detail": "An internal server error occurred while fetching status."}

@router.post(
    "/ask/{transcript_id}/",
    response={
        200: AnswerOut,
        400: ErrorDetail,
        404: ErrorDetail,
        500: ErrorDetail,
        503: ErrorDetail,
    }, auth=AsyncJWTAuth(),
    summary="Ask a Question (RAG)",
    description="Ask a question about a transcript. Uses RAG to retrieve relevant context and generate an answer."
)
async def ask_question(request, transcript_id: int, payload: QuestionIn):
    try:
        transcript = await sync_to_async(get_object_or_404)(
            Transcript.objects.only('id', 'embedding_status'),
            id=transcript_id
        )
        if transcript.embedding_status != EmbeddingStatusEnum.COMPLETED:
            logger.warning(f"Attempted Q&A for tx {transcript_id} but embedding status is '{transcript.embedding_status}'.")
            status_detail = f"Embeddings for transcript {transcript_id} are not ready (Status: {transcript.embedding_status}). Please wait or check status again later."
            return 400, {"detail": status_detail}

    except Http404:
        return 404, {"detail": f"Transcript with id {transcript_id} not found."}
    except Exception as e:
        logger.error(f"Error checking transcript status for Q&A (tx {transcript_id}): {e}", exc_info=True)
        return 500, {"detail": "Failed to check transcript status."}
    try:
        mistral_service = MistralService()
        logger.debug(f"Embedding question for tx {transcript_id}: '{payload.question[:50]}...'")
        question_embedding = await sync_to_async(mistral_service.get_query_embedding)(payload.question)
        logger.debug(f"Question embedding generated (shape: {question_embedding.shape}).")
    except Exception as e:
        logger.error(f"Failed to initialize MistralService or embed question for tx {transcript_id}: {e}", exc_info=True)
        return 503, {"detail": f"Could not process question embedding: {e}"}
    retrieved_nodes_with_scores: List[NodeWithScore] = []
    try:
        vector_store: PGVectorStore = await sync_to_async(get_vector_store)()
        custom_filters = MetadataFilters(filters=[MetadataFilter(key="transcript_id", value=transcript_id, operator=FilterOperator.EQ)])
        query = VectorStoreQuery(
            query_embedding=question_embedding.tolist(),
            similarity_top_k=3,
            filters=custom_filters,
        )
        logger.debug(f"Querying vector store for tx {transcript_id} with filters and top_k=3.")
        query_result = await sync_to_async(vector_store.query)(query)
        retrieved_nodes = query_result.nodes if query_result else []
        retrieved_context = [node.get_content() for node in retrieved_nodes]
        logger.info(f"Retrieved {len(retrieved_context)} context chunks for tx {transcript_id}.")
        if not retrieved_context:
            logger.warning(f"No relevant context found in vector store for question about tx {transcript_id}.")

    except ImportError:
         logger.error("LlamaIndex PGVectorStore or query components not found.")
         return 500, {"detail": "Vector store components not available."}
    except Exception as e:
        logger.error(f"Error querying vector store for tx {transcript_id}: {e}", exc_info=True)
        return 500, {"detail": "Failed to retrieve context from vector store."}

    try:
        context_str = "\n\n---\n\n".join(retrieved_context)
        system_prompt = "You are a helpful assistant answering questions based ONLY on the provided context from a meeting transcript. If the context doesn't contain the answer, say 'The provided context does not contain the answer to this question.' Do not make up information."
        user_prompt = f"""
        Context from the transcript:
        ---
        {context_str if context_str else "No relevant context found."}
        ---

        Question: {payload.question}

        Answer based only on the context:
        """

        logger.debug(f"Generating final answer for tx {transcript_id} using chat model.")
        final_answer = await sync_to_async(mistral_service.generate_response)(
            system_prompt=system_prompt,
            user_prompt=user_prompt
        )
        logger.info(f"Generated answer for tx {transcript_id}.")

        return 200, {"answer": final_answer}

    except ConnectionError as e:
         logger.error(f"Connection error during final LLM call for tx {transcript_id}: {e}", exc_info=True)
         return 503, {"detail": f"Could not connect to the language model service: {e}"}
    except Exception as e:
        logger.error(f"Error generating final answer using LLM for tx {transcript_id}: {e}", exc_info=True)
        return 500, {"detail": f"Failed to generate answer: {e}"}