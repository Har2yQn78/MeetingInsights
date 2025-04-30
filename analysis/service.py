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
        system_message = """
        You are an AI assistant that processes meeting transcripts. Your SOLE function is to return a valid JSON object containing the extracted information based on the user's request.
        ABSOLUTELY DO NOT include any conversational text, greetings, introductions, explanations, apologies, summaries of your process, or any text whatsoever before or after the JSON object.
        Your entire response MUST start with '{' and end with '}'. You MUST adhere to the JSON structure provided by the user.
        Output ONLY the JSON.
        """

        user_prompt = f"""
        Analyze the following meeting transcript provided below.
        Extract the required information accurately and concisely.
        Your response MUST be formatted STRICTLY as a single JSON object containing ONLY the keys specified in the 'Required JSON Output Structure' section below. Use JSON null for missing information.

        Reference Date for relative date calculation (e.g., "next Tuesday"): {today.strftime('%Y-%m-%d %A')}

        Transcript to Analyze:
        --- START TRANSCRIPT ---
        {transcript_text}
        --- END TRANSCRIPT ---

        Required JSON Output Structure (ONLY output this structure as JSON):
        {{
          "transcript_title": "Concise title (5-10 words) summarizing THIS transcript's main topic. Use null if unclear.",
          "summary": "A 2-3 paragraph summary of key discussion points and outcomes from THIS transcript.",
          "key_points": ["List of 2-4 most important points/decisions as strings."],
          "task": "The single most prominent action item/task mentioned. Use null if none.",
          "responsible": "Person/team assigned to the action item. Use null if not specified.",
          "deadline": "Deadline for action item (YYYY-MM-DD format, converting relative dates based on reference date). Use null if not mentioned."
        }}

        REMEMBER: Your final output MUST be ONLY the JSON object, starting with '{{' and ending with '}}'. No other text is allowed.
        and also REMEMBER to always return the summary and key_points
        """

        content = None
        try:
            logger.info(f"Sending request to OpenRouter model: {self.model}...")
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={ "type": "json_object" },
                temperature=0.0
            )

            if not response.choices or not response.choices[0].message or response.choices[0].message.content is None:
                 err_msg = "Invalid or empty response structure received from LLM."
                 logger.error(err_msg + f" Response object: {response}")
                 raise ValueError(err_msg)

            content = response.choices[0].message.content
            logger.debug(f"Raw response content from LLM: {content}")

            if not content.strip():
                 logger.error("LLM returned empty string content. Cannot process.")
                 raise ValueError("LLM returned empty string content.")

            data = None
            try:
                data = json.loads(content)
                logger.info("Successfully parsed JSON directly.")
            except json.JSONDecodeError as e_direct:
                logger.warning(f"Direct JSON parsing failed ({e_direct}). Attempting extraction/cleanup.")
                try:
                    start_index = content.find('{')
                    end_index = content.rfind('}')
                    if start_index != -1 and end_index != -1 and end_index > start_index:
                        json_str = content[start_index : end_index + 1]
                        data = json.loads(json_str)
                        logger.info("Successfully parsed JSON after extracting bracketed content.")
                    else:
                         content_stripped = content.strip()
                         if content_stripped.startswith("```") and content_stripped.endswith("```"):
                             cleaned_content = content_stripped.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                             data = json.loads(cleaned_content)
                             logger.info("Successfully parsed JSON after cleaning markdown fences.")
                         else:
                             logger.error(f"Could not extract valid JSON. Content excerpt: {content[:500]}...")
                             raise ValueError(f"LLM returned non-JSON data and cleanup failed. Content excerpt: {content[:500]}...")
                except json.JSONDecodeError as json_e_clean:
                     logger.error(f"JSON parsing failed even after extraction/cleanup attempt: {json_e_clean}. Content excerpt: {content[:500]}...")
                     raise ValueError(f"LLM returned non-JSON data after cleanup attempt: {json_e_clean}. Content excerpt: {content[:500]}...")

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

            logger.info(f"Successfully extracted and processed analysis results.")
            return analysis_results

        except RateLimitError as e:
            logger.error(f"OpenRouter Rate Limit Error: {e}", exc_info=True)
            raise ConnectionAbortedError(f"Rate limit hit with LLM provider: {e}") from e
        except APIError as e:
            logger.error(f"OpenRouter API Error: {e}", exc_info=True)
            raise ConnectionAbortedError(f"API error from LLM provider: {e}") from e
        except (ValueError, json.JSONDecodeError) as e:
             logged_content_excerpt = content[:500] + "..." if content is not None else "Content unavailable or None"
             logger.error(f"Error parsing/processing LLM response: {e}. Content excerpt was: {logged_content_excerpt}", exc_info=True)
             raise ValueError(f"Failed to process analysis result from LLM: {e}. Response excerpt: {logged_content_excerpt}") from e
        except ConnectionError as e:
             logger.error(f"LLM Client Connection Error: {e}", exc_info=True)
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
             logger.error(f"Error executing async analysis via sync wrapper: {type(e).__name__} - {e}", exc_info=True)
             raise e