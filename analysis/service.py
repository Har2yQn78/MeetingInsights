import os
import json
from typing import Any, Dict
from django.conf import settings
from decouple import config, AutoConfig
import openai

config = AutoConfig(search_path="/home/harry/meetinginsight")
OPENROUTER_API_KEY = config("OPENROUTER_API_KEY", cast=str)
# OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", settings.OPENROUTER_API_KEY)

openai.api_key = OPENROUTER_API_KEY
openai.api_base = "https://openrouter.ai/api/v1"

class TranscriptAnalysisService:
    def __init__(self, model_name: str = "google/gemini-2.5-pro-exp-03-25:free"):
        self.model = model_name

    async def analyze_transcript(self, transcript_text: str) -> Dict[str, Any]:
        prompt = f"""
        Analyze the following meeting transcript and provide:
        1. A concise summary (2-3 paragraphs)
        2. 5-7 key points discussed in the meeting
        3. Action items with responsible person and deadline (if mentioned)

        Format the output as JSON with the following structure:
        {{
            "summary": "Summary text here...",
            "key_points": ["Point 1", "Point 2", ...],
            "task": "Describe the task here...",
            "responsible": "Person or entity responsible...",
            "deadline": "YYYY-MM-DD"
        }}

        Meeting Transcript:
        {transcript_text}
        """

        try:
            response = await openai.ChatCompletion.acreate(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.choices[0].message["content"]
            if content.strip().startswith("```"):
                content = content.strip().lstrip("```json").rstrip("```").strip()

            data = json.loads(content)

            # Format the response to match the expected structure in our API
            return {
                "summary": data.get("summary", ""),
                "key_points": data.get("key_points", []),
                "action_items": {
                    "task": data.get("task", ""),
                    "responsible": data.get("responsible", ""),
                    "deadline": data.get("deadline", None)
                }
            }

        except Exception as e:
            return {
                "summary": f"Error analyzing transcript: {str(e)}",
                "key_points": [],
                "action_items": {
                    "task": "",
                    "responsible": "",
                    "deadline": None
                }
            }