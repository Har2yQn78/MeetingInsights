from ninja import Schema
from pydantic import Field, validator, ConfigDict
from datetime import datetime
from typing import Optional, List, Dict, Any

class MeetingSchemaOut(Schema):
    id: int = Field(..., description="Unique identifier for the meeting.")
    title: str = Field(..., description="The title or subject of the meeting.")
    meeting_date: datetime = Field(..., description="The date and time when the meeting occurred (UTC).")
    participants: Optional[List[Any]] = Field(None, description="A list of participants who attended the meeting. Can contain strings or objects.")
    metadata: Optional[Dict[str, Any]] = Field(None, description="A flexible JSON field for storing additional unstructured metadata about the meeting.")
    created_at: datetime = Field(..., description="Timestamp when the meeting record was created (UTC).")
    updated_at: datetime = Field(..., description="Timestamp when the meeting record was last updated (UTC).")

class MeetingSchemaIn(Schema):
    title: str = Field(..., min_length=3, max_length=255, description="The title or subject of the meeting (must not be empty).")
    meeting_date: Optional[datetime] = Field(None, description="The date and time the meeting occurred. Defaults to the time of creation if not provided.")
    participants: Optional[List[Any]] = Field(None, description="List of participant names or identifiers.")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional flexible key-value store for additional meeting metadata.")

    @validator('title')
    def title_must_not_be_empty(cls, v):
        if not v.strip():
            raise ValueError('Title cannot be empty or just whitespace')
        return v

class MeetingSchemaUpdate(Schema):
    title: Optional[str] = Field(None, min_length=3, max_length=255, description="New title for the meeting.")
    meeting_date: Optional[datetime] = Field(None, description="New date and time for the meeting.")
    participants: Optional[List[Any]] = Field(None, description="Updated list of participants.")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Updated or new metadata. This will replace the existing metadata.")

    @validator('title', pre=True, always=True)
    def title_must_not_be_empty_if_provided(cls, v):
        if v is not None and not v.strip():
            raise ValueError('Title cannot be empty or just whitespace')
        return v


class ErrorDetail(Schema):
    detail: str = Field(..., description="A message describing the error that occurred.")