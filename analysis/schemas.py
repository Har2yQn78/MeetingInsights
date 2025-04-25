from ninja import Schema
from pydantic import Field
from datetime import datetime, date
from typing import Optional, List

class AnalysisResultSchemaOut(Schema):
    transcript_id: int = Field(...)
    summary: Optional[str] = Field(None)
    key_points: Optional[List[str]] = Field(None)
    task: str = Field(...)
    responsible: Optional[str] = Field(None)
    deadline: Optional[date] = Field(None) # (format: YYYY-MM-DD)
    created_at: datetime = Field(...)
    updated_at: datetime = Field(...)

class DirectProcessInput(Schema):
    raw_text: Optional[str] = None


class AnalysisCreateSchema(Schema):
    transcript_id: int

class ErrorDetail(Schema):
    detail: str