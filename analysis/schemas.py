from ninja import Schema
from pydantic import Field
from datetime import datetime
from typing import Optional, List, Any

class ActionItemSchema(Schema):
    task: str = Field(..., description="The description of the action item.")
    responsible: Optional[str] = Field(None, description="The person or entity assigned the task.")
    deadline: Optional[str] = Field(None, description="The deadline for the task (as text, e.g., 'YYYY-MM-DD' or 'Next Friday').")
class AnalysisResultSchemaOut(Schema):
    transcript_id: int = Field(..., description="The ID of the associated transcript (which is also the primary key of this analysis).")
    summary: Optional[str] = Field(None, description="The generated text summary of the transcript.")
    key_points: Optional[List[str]] = Field(None, description="A list of key points extracted from the transcript.")
    action_items: Optional[List[ActionItemSchema]] = Field(None, description="A list of structured action items extracted from the transcript.")
    created_at: datetime = Field(..., description="Timestamp when the analysis result was created.")
    updated_at: datetime = Field(..., description="Timestamp when the analysis result was last updated.")
