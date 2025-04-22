from ninja import Schema
from pydantic import Field, validator
from datetime import datetime
from typing import Optional, List, Dict, Any

class MeetingSchemaOut(Schema):
    id: int
    title: str
    meeting_date: datetime
    participants: Optional[List[Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

class MeetingSchemaIn(Schema):
    title: str = Field(..., min_length=3, max_length=255)
    meeting_date: Optional[datetime] = Field(None)
    participants: Optional[List[Any]] = Field(None)
    metadata: Optional[Dict[str, Any]] = Field(None)
    @validator('title')
    def title_must_not_be_empty(cls, v):
        if not v.strip():
            raise ValueError('Title cannot be empty or just whitespace')
        return v

class MeetingSchemaUpdate(Schema):
    title: Optional[str] = Field(None, min_length=3, max_length=255)
    meeting_date: Optional[datetime] = Field(None)
    participants: Optional[List[Any]] = Field(None)
    metadata: Optional[Dict[str, Any]] = Field(None)

    @validator('title', pre=True, always=True)
    def title_must_not_be_empty_if_provided(cls, v):
        if v is not None and not v.strip():
            raise ValueError('Title cannot be empty or just whitespace')
        return v

class ErrorDetail(Schema):
    detail: str

