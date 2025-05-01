from ninja import Schema
from pydantic import Field
from datetime import datetime
from typing import Optional
import enum
from transcripts.models import Transcript as TranscriptModel

class EmbeddingStatusEnum(str, enum.Enum):
    NONE = TranscriptModel.EmbeddingStatus.NONE
    PENDING = TranscriptModel.EmbeddingStatus.PENDING
    PROCESSING = TranscriptModel.EmbeddingStatus.PROCESSING
    COMPLETED = TranscriptModel.EmbeddingStatus.COMPLETED
    FAILED = TranscriptModel.EmbeddingStatus.FAILED

class EmbeddingStatusOut(Schema):
    transcript_id: int = Field
    embedding_status: EmbeddingStatusEnum = Field
    updated_at: datetime = Field

class QuestionIn(Schema):
    question: str = Field

class AnswerOut(Schema):
    answer: str = Field

class ErrorDetail(Schema):
    detail: str = Field