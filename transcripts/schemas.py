from ninja import Schema
from pydantic import Field, AnyUrl
from datetime import datetime
from typing import Optional
import enum

from .models import Transcript as TranscriptModel

class ProcessingStatusEnum(str, enum.Enum):
    PENDING = TranscriptModel.ProcessingStatus.PENDING
    PROCESSING = TranscriptModel.ProcessingStatus.PROCESSING
    COMPLETED = TranscriptModel.ProcessingStatus.COMPLETED
    FAILED = TranscriptModel.ProcessingStatus.FAILED

class TranscriptSchemaIn(Schema):
    raw_text: str = Field(..., min_length=10, description="The raw text content of the meeting transcript.")

class TranscriptSchemaOut(Schema):
    id: int
    meeting_id: int
    raw_text: str
    processing_status: ProcessingStatusEnum
    processing_error: Optional[str] = None
    original_file_url: Optional[AnyUrl] = None
    async_task_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_meeting_id(obj: TranscriptModel):
        return obj.meeting_id

    @staticmethod
    def resolve_original_file_url(obj: TranscriptModel):
        if obj.original_file:
            try:
                return obj.original_file.url
            except Exception:
                return None
        return None

class TranscriptStatusSchemaOut(Schema):
    id: int
    meeting_id: int
    processing_status: ProcessingStatusEnum
    processing_error: Optional[str] = None
    original_file_url: Optional[AnyUrl] = None
    updated_at: datetime

    @staticmethod
    def resolve_meeting_id(obj: TranscriptModel):
        return obj.meeting_id

    @staticmethod
    def resolve_original_file_url(obj: TranscriptModel):
        if obj.original_file:
            try:
                return obj.original_file.url
            except Exception:
                return None
        return None

class ErrorDetail(Schema):
    detail: str