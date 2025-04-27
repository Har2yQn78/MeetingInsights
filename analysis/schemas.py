from ninja import Schema
from pydantic import Field
from datetime import datetime, date
from typing import Optional, List

class AnalysisResultSchemaOut(Schema):
    transcript_id: int = Field(..., description="The transcript id")
    summary: Optional[str] = Field(None, description="The summary of the analysis")
    key_points: Optional[List[str]] = Field(None, description="The keypoints of the analysis")
    task: str = Field(..., description="The task of the analysis")
    responsible: Optional[str] = Field(None, description="The responsible of the analysis")
    deadline: Optional[date] = Field(None, description="(format: YYYY-MM-DD)")
    created_at: datetime = Field(...)
    updated_at: datetime = Field(...)

class DirectProcessInput(Schema):
    raw_text: Optional[str] = None


class AnalysisCreateSchema(Schema):
    transcript_id: int

class ErrorDetail(Schema):
    detail: str