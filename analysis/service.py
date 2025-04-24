import os
import json
import logging # Import logging
from typing import Any, Dict
from django.conf import settings
from decouple import config, AutoConfig
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

config = AutoConfig(search_path="/home/harry/meetinginsight")
OPENROUTER_API_KEY = config("OPENROUTER_API_KEY", cast=str)
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"

if not OPENROUTER_API_KEY:
    logger.error("OPENROUTER_API_KEY not found. Please set it in your .env file or environment variables.")

client = AsyncOpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url=OPENROUTER_API_BASE,
)

class TranscriptAnalysisService:
    def __init__(self, model_name: str = "google/gemma-3-12b-it:free"):
        self.model = model_name

    async def analyze_transcript(self, transcript_text: str) -> Dict[str, Any]:
        if not OPENROUTER_API_KEY:
             logger.error("Cannot analyze transcript: OPENROUTER_API_KEY is missing.")
             raise ValueError("OpenAI API key is not configured.")

        prompt = f"""
        Analyze the following meeting transcript and provide:
        1. A concise summary (2-3 paragraphs)
        2. 5-7 key points discussed in the meeting
        3. Action items, including task description, responsible person/entity, and deadline (if mentioned). If multiple action items exist, list them or summarize the primary ones clearly within the 'task' field or add an 'action_items_list' field.

        Format the output STRICTLY as JSON with the following structure:
        {{
            "summary": "String summary text here...",
            "key_points": ["List", "of", "string", "key points"],
            "task": "String describing the main task or a summary of tasks...",
            "responsible": "String identifying the person or entity responsible...",
            "deadline": "String in YYYY-MM-DD format or null/empty string if not specified"
        }}

        Meeting Transcript:
        ---
        {transcript_text}
        ---

        JSON Output:
        """

        try:
            logger.info(f"Sending request to OpenRouter model: {self.model}")
            response = await client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={ "type": "json_object" }
            )

            content = response.choices[0].message.content
            logger.debug(f"Raw response content from LLM: {content}")
            if content:
                if content.strip().startswith("{") and content.strip().endswith("}"):
                   data = json.loads(content)
                else:
                    logger.warning("LLM response was not valid JSON despite requesting JSON format. Attempting manual extraction or returning error.")
                    try:
                        if content.strip().startswith("```"):
                             cleaned_content = content.strip().lstrip("```json").rstrip("```").strip()
                             data = json.loads(cleaned_content)
                        else:
                             raise json.JSONDecodeError("Response is not JSON", content, 0)
                    except json.JSONDecodeError as json_e:
                        logger.error(f"Failed to parse LLM response as JSON: {json_e}. Response: {content}")
                        raise ValueError(f"LLM returned non-JSON data: {content[:100]}...")
            else:
                 logger.error("Received empty content from LLM.")
                 raise ValueError("LLM returned empty content.")
            summary = data.get("summary", "")
            key_points = data.get("key_points", [])
            task = data.get("task", "")
            responsible = data.get("responsible", "")
            deadline = data.get("deadline")

            if not isinstance(key_points, list): key_points = []
            if not isinstance(summary, str): summary = str(summary)
            if not isinstance(task, str): task = str(task)
            if not isinstance(responsible, str): responsible = str(responsible)
            if deadline is not None and not isinstance(deadline, str):
                deadline = str(deadline)
            elif deadline == "":
                deadline = None

            return {
                "summary": summary,
                "key_points": key_points,
                "action_items": {
                    "task": task,
                    "responsible": responsible,
                    "deadline": deadline
                }
            }

        except json.JSONDecodeError as e:
             logger.error(f"JSON Decode Error analyzing transcript: {e}. Content was: {content}", exc_info=True)
             raise ValueError(f"Failed to parse analysis result from LLM: {e}") from e
        except Exception as e:

            logger.error(f"Error analyzing transcript with model {self.model}: {e}", exc_info=True)
            raise