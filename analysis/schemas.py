from ninja import Schema
from pydantic import Field
from datetime import datetime, date
from typing import Optional, List


class AnalysisResultSchemaOut(Schema):
    transcript_id: int = Field(..., description="The ID of the associated transcript.")
    transcript_title: Optional[str] = Field(None, description="Title generated for the transcript during analysis.")
    summary: Optional[str] = Field(None, description="The summary of the analysis.")
    key_points: Optional[List[str]] = Field(None, description="The keypoints of the analysis.")
    task: Optional[str] = Field(None, description="The task of the analysis.")
    responsible: Optional[str] = Field(None, description="The responsible of the analysis.")
    deadline: Optional[date] = Field(None, description="(format: YYYY-MM-DD)")
    created_at: datetime = Field(...)
    updated_at: datetime = Field(...)

    @staticmethod
    def resolve_transcript_title(obj: 'AnalysisResult') -> Optional[str]:
        try:
            if hasattr(obj, 'transcript') and obj.transcript and hasattr(obj.transcript, 'title'):
                return obj.transcript.title
            else:
                return None
        except AttributeError:
            return None


class DirectProcessInput(Schema):
    raw_text: Optional[str] = None

class ErrorDetail(Schema):
    detail: str

class PaginatedAnalysisResponse(Schema):
    count: int = Field(..., description="Total number of analysis results available.")
    offset: int = Field(..., description="The starting index (offset) of the returned items.")
    limit: int = Field(..., description="The maximum number of items requested per page.")
    items: List[AnalysisResultSchemaOut] = Field(..., description="The list of analysis results for the current page.")