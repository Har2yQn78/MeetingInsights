from ninja import Schema
from pydantic import Field
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
    title: Optional[str] = Field(None, description="Title generated for this specific transcript during analysis.")
    raw_text: Optional[str]
    processing_status: ProcessingStatusEnum
    processing_error: Optional[str] = None
    original_file_url: Optional[str] = None
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

    @staticmethod
    def resolve_raw_text(obj: TranscriptModel):
         return obj.raw_text if obj.raw_text else None


class TranscriptStatusSchemaOut(Schema):
    id: int
    meeting_id: int
    title: Optional[str] = Field(None, description="Title generated for this specific transcript during analysis.") # <--- ADDED FIELD
    processing_status: ProcessingStatusEnum
    processing_error: Optional[str] = None
    original_file_url: Optional[str] = None
    updated_at: datetime
    async_task_id: Optional[str] = None

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