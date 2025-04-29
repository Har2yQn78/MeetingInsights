import os
import json
import logging
import asyncio
from typing import Any, Dict, Optional, List
from datetime import datetime, date, timedelta
from django.conf import settings
from decouple import config, AutoConfig
from openai import AsyncOpenAI, RateLimitError, APIError
from dateutil.parser import parse as dateutil_parse

logger = logging.getLogger(__name__)
config_search_path = settings.BASE_DIR if hasattr(settings, 'BASE_DIR') else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
config = AutoConfig(search_path=config_search_path)

OPENROUTER_API_KEY = config("OPENROUTER_API_KEY", default=None)
OPENROUTER_API_BASE = config("OPENROUTER_API_BASE", default="https://openrouter.ai/api/v1")
LLM_MODEL_NAME = config("LLM_MODEL_NAME", default="deepseek/deepseek-r1:free")

client = None
if not OPENROUTER_API_KEY:
    logger.error("OPENROUTER_API_KEY not found. Please set it in your .env file or environment variables.")
else:
    try:
        client = AsyncOpenAI(api_key=OPENROUTER_API_KEY, base_url=OPENROUTER_API_BASE)
        logger.info(f"OpenRouter client initialized for model {LLM_MODEL_NAME} via base URL {OPENROUTER_API_BASE}")
    except Exception as e:
        logger.error(f"Failed to initialize OpenRouter client: {e}", exc_info=True)
        client = None


class TranscriptAnalysisService:
    def __init__(self, model_name: str = LLM_MODEL_NAME):
        self.model = model_name

    def _parse_relative_date(self, date_str: Optional[str], reference_date: date) -> Optional[date]:
        if not date_str or not isinstance(date_str, str):
            return None
        date_str = date_str.strip()
        if not date_str:
            return None

        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            try:
                dt = dateutil_parse(date_str, default=datetime.combine(reference_date, datetime.min.time()))
                return dt.date()
            except (ValueError, TypeError, OverflowError) as e:
                logger.warning(f"Could not parse date string '{date_str}' using dateutil: {e}")
                return None

    async def analyze_transcript(self, transcript_text: str) -> Dict[str, Any]:
        if not client:
             logger.error("Cannot analyze transcript: OpenRouter client is not initialized.")
             raise ConnectionError("LLM client is not configured or initialization failed.")

        today = datetime.now().date()
        prompt = f"""
        Analyze the following meeting transcript. Extract the requested information accurately and concisely.
        Format the output STRICTLY as a JSON object with the specified keys. Use null for missing information.

        Reference Date for relative date calculation (e.g., "next Tuesday"): {today.strftime('%Y-%m-%d %A')}

        Transcript:
        ---
        {transcript_text}
        ---

        Required JSON Output Structure:
        {{
          "transcript_title": "Concise title (5-10 words) summarizing THIS transcript's main topic. Use null if unclear.",
          "summary": "A 2-3 paragraph summary of key discussion points and outcomes from THIS transcript.",
          "key_points": ["List of 2-4 most important points/decisions as strings."],
          "task": "The single most prominent action item/task mentioned. Use null if none.",
          "responsible": "Person/team assigned to the action item. Use null if not specified.",
          "deadline": "Deadline for action item (YYYY-MM-DD format, converting relative dates). Use null if not mentioned."
        }}

        JSON Output Only:
        """

        try:
            logger.info(f"Sending request to OpenRouter model: {self.model}...")
            response = await client.chat.completions.create(model=self.model, messages=[{"role": "user", "content": prompt}], response_format={ "type": "json_object" })
            if not response.choices or not response.choices[0].message:
                 logger.error("Invalid response structure received from LLM: Missing choices or message.")
                 raise ValueError("Invalid response structure from LLM.")
            content = response.choices[0].message.content
            logger.debug(f"Raw response content from LLM: {content}")
            if content is None or not content.strip():
                 logger.error("LLM returned None or empty content. Cannot process.")
                 raise ValueError("LLM returned empty or None content.")
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                 logger.warning("LLM response not valid JSON. Attempting cleanup.")
                 if content.strip().startswith("```") and content.strip().endswith("```"):
                      cleaned_content = content.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                      try:
                           data = json.loads(cleaned_content)
                           logger.info("Successfully parsed JSON after cleanup.")
                      except json.JSONDecodeError as json_e_clean:
                           logger.error(f"JSON cleanup failed: {json_e_clean}. Resp: {content[:500]}...")
                           raise ValueError(f"LLM returned non-JSON data after cleanup attempt.")
                 else:
                      logger.error(f"JSON parse failed, no cleanup markers. Resp: {content[:500]}...")
                      raise ValueError(f"LLM returned non-JSON data.")
            extracted_title = data.get("transcript_title")
            summary = data.get("summary")
            key_points = data.get("key_points", [])
            task = data.get("task")
            responsible = data.get("responsible")
            deadline_str = data.get("deadline")
            analysis_results = {}
            analysis_results["transcript_title"] = str(extracted_title) if extracted_title is not None else None
            analysis_results["summary"] = str(summary) if summary is not None else None
            if isinstance(key_points, list):
                 analysis_results["key_points"] = [str(item) for item in key_points]
            else:
                 logger.warning(f"Key points field was not a list ({type(key_points)}), defaulting to empty.")
                 analysis_results["key_points"] = []
            analysis_results["task"] = str(task) if task is not None else None
            analysis_results["responsible"] = str(responsible) if responsible is not None else None
            analysis_results["deadline"] = self._parse_relative_date(deadline_str, today)
            logger.info(f"Successfully extracted analysis results.")
            return analysis_results

        except RateLimitError as e:
            logger.error(f"OpenRouter Rate Limit Error: {e}", exc_info=True)
            raise ConnectionAbortedError(f"Rate limit hit with LLM provider: {e}") from e
        except APIError as e:
            logger.error(f"OpenRouter API Error: {e}", exc_info=True)
            raise ConnectionAbortedError(f"API error from LLM provider: {e}") from e
        except (ValueError, json.JSONDecodeError) as e:
             logged_content = content[:500] + "..." if 'content' in locals() and content is not None else "Content unavailable or None"
             logger.error(f"Error parsing/processing LLM response: {e}. Content was: {logged_content}", exc_info=True)
             raise ValueError(f"Failed to process analysis result from LLM: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error during transcript analysis with model {self.model}: {e}", exc_info=True)
            raise RuntimeError(f"An unexpected error occurred during transcript analysis: {e}") from e

    def analyze_transcript_sync(self, transcript_text: str) -> Dict[str, Any]:
        logger.info("Running analyze_transcript asynchronously via sync wrapper...")
        try:
            result = asyncio.run(self.analyze_transcript(transcript_text))
            logger.info("Async analysis completed successfully via sync wrapper.")
            return result
        except Exception as e:
             logger.error(f"Error executing async analysis via sync wrapper: {e}", exc_info=True)
             raise e