from ninja import Schema
from pydantic import Field
from datetime import datetime, date
from typing import Optional, List
from transcripts.models import Transcript as TranscriptModel

class AnalysisResultSchemaOut(Schema):
    transcript_id: int = Field(..., description="The transcript id")
    transcript_title: Optional[str] = Field(None, description="Title generated for the transcript during analysis.")
    summary: Optional[str] = Field(None, description="The summary of the analysis")
    key_points: Optional[List[str]] = Field(None, description="The keypoints of the analysis")
    task: Optional[str] = Field(None, description="The task of the analysis")
    responsible: Optional[str] = Field(None, description="The responsible of the analysis")
    deadline: Optional[date] = Field(None, description="(format: YYYY-MM-DD)")
    created_at: datetime = Field(...)
    updated_at: datetime = Field(...)

    @staticmethod
    def resolve_transcript_title(obj: 'AnalysisResult') -> Optional[str]:
        try:
            if hasattr(obj, 'transcript') and obj.transcript:
                return obj.transcript.title
            else:
                transcript = TranscriptModel.objects.get(pk=obj.transcript_id)
                return transcript.title
        except TranscriptModel.DoesNotExist:
            return None
        except AttributeError:
            return None

class DirectProcessInput(Schema):
    raw_text: Optional[str] = None

class ErrorDetail(Schema):
    detail: str

class PaginatedAnalysisResponse(Schema):
    count: int = Field(...)
    offset: int = Field(...)
    limit: int = Field(...)
    items: List[AnalysisResultSchemaOut] = Field(...)