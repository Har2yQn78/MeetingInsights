from ninja import Schema
from pydantic import Field
from datetime import datetime, date
from typing import Optional, List

class AnalysisResultSchemaOut(Schema):
    transcript_id: int = Field(..., description="The ID of the related transcript.")
    summary: Optional[str] = Field(None, description="The generated text summary of the transcript.")
    key_points: Optional[List[str]] = Field(None, description="A list of key points extracted from the transcript.")
    task: str = Field(..., description="The task extracted from the transcript.")
    responsible: Optional[str] = Field(None, description="The person or entity assigned to the task.")
    deadline: Optional[date] = Field(None, description="The deadline for the task (format: YYYY-MM-DD).")
    created_at: datetime = Field(..., description="The timestamp when the analysis was created.")
    updated_at: datetime = Field(..., description="The timestamp when the analysis was last updated.")

class AnalysisCreateSchema(Schema):
    transcript_id: int

class ErrorDetail(Schema):
    detail: str