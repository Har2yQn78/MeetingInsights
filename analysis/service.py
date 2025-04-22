import os
import google.generativeai as genai
from typing import Dict, List, Any, Optional
from django.conf import settings
from decouple import config, AutoConfig


GEMINI_API_KEY = config("GEMINI_API_KEY", cast=str)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", settings.GEMINI_API_KEY)
genai.configure(api_key=GEMINI_API_KEY)


class GeminiAnalysisService:
    def __init__(self, model_name="gemini-1.5-pro"):
        self.model = genai.GenerativeModel(model_name)

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
            "action_items": [
                {{"task": "Task description", "responsible": "Person name", "deadline": "Date or timeframe"}}
            ]
        }}

        Meeting Transcript:
        {transcript_text}
        """

        try:
            response = await self.model.generate_content_async(prompt)
            import json
            content = response.text
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            analysis_data = json.loads(content)
            result = {
                'summary': analysis_data.get('summary', ''),
                'key_points': analysis_data.get('key_points', []),
                'action_items': analysis_data.get('action_items', [])
            }

            return result

        except Exception as e:
            print(f"Error analyzing transcript with Gemini: {str(e)}")
            return {
                'summary': f"Error analyzing transcript: {str(e)}",
                'key_points': [],
                'action_items': []
            }