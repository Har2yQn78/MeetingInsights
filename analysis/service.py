import os
import json
import logging
import asyncio
from typing import Any, Dict, Optional
from datetime import datetime, date, timedelta
from django.conf import settings
from decouple import config, AutoConfig
from openai import AsyncOpenAI
from dateutil.parser import parse as dateutil_parse

logger = logging.getLogger(__name__)

config = AutoConfig(search_path="/home/harry/meetinginsight")
OPENROUTER_API_KEY = config("OPENROUTER_API_KEY", default=None)
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"

if not OPENROUTER_API_KEY:
    logger.error("OPENROUTER_API_KEY not found. Please set it in your .env file or environment variables.")

client = None
if OPENROUTER_API_KEY:
    client = AsyncOpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_API_BASE,
    )
else:
    logger.warning("OpenRouter client not initialized because OPENROUTER_API_KEY is missing.")


class TranscriptAnalysisService:
    def __init__(self, model_name: str = "deepseek/deepseek-chat-v3-0324:free"):
        self.model = model_name

    def _parse_relative_date(self, date_str: Optional[str], reference_date: date) -> Optional[date]:
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
             logger.error("Cannot analyze transcript: OpenRouter client is not initialized (API key missing?).")
             raise ValueError("OpenAI API key is not configured or client initialization failed.")

        today = datetime.now().date()
        prompt = f"""
        Role: Expert Meeting Analyst and Information Extractor
        Task: You are a highly skilled meeting analyst who extracts key information from meeting transcripts with precision. Your job is to analyze the provided transcript and extract specific data points in a structured format.
         Guidelines
        - Extract only information that is explicitly mentioned or can be reasonably inferred from the transcript
        - Use clear, accurate language in your extractions
        - Format dates consistently in YYYY-MM-DD format
        - Be precise with participant names and roles
        - When information is not available, use null in the JSON response
        - Prioritize accuracy over completeness
        Reference Information
        Today's date for relative date calculations: {today.strftime('%Y-%m-%d %A')}
        Required Extraction Fields
        1. Meeting Title: Create a concise, descriptive title based on the primary topic discussed. Use null if no clear topic emerges.

        2. Meeting Date: Extract when the meeting occurred in YYYY-MM-DD format. Convert relative dates like "yesterday" or "next Tuesday" based on the reference date provided. Use null if not mentioned.
        
        3. Participants: Identify all attendees mentioned by name. Return as a list of strings. Return empty list [] if none are mentioned.
        
        4. Summary: Provide a concise 2-3 paragraph overview capturing the main discussion points and outcomes. Focus on substance rather than process.
        
        5. Key Points: Extract 2-4 most important discussion points or decisions. Format as a list of clear, standalone statements.
        
        6. Action Item - Task: Identify the primary action item or task discussed. If multiple exist, include the most critical one or summarize them. Use null if none mentioned.
        
        7. Action Item - Responsible: Identify the person or team assigned to the action item. Use null if not specified.
        
        8. Action Item - Deadline: Extract the deadline for the task in YYYY-MM-DD format. Convert relative timeframes like "in two weeks" or "by month-end" based on the reference date. Use null if not mentioned.

        Format the output STRICTLY as JSON with the following structure:
        {{
            "meeting_title": "String title or null",
            "meeting_date_extracted": "YYYY-MM-DD string or null",
            "participants_extracted": ["Participant Name 1", "Participant Name 2"],
            "summary": "String summary text...",
            "key_points": ["List", "of", "string", "key points"],
            "task": "String task description or null",
            "responsible": "String responsible name or null",
            "deadline": "YYYY-MM-DD string or null"
        }}

        Reference Date for relative dates: {today.strftime('%Y-%m-%d %A')}

        Meeting Transcript:
        ---
        {transcript_text}
        ---

        JSON Output:
        """

        try:
            logger.info(f"Sending request to OpenRouter model: {self.model} for transcript analysis (async call)")
            response = await client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={ "type": "json_object" }
            )

            content = response.choices[0].message.content
            logger.debug(f"Raw response content from LLM: {content}")

            if not content:
                 logger.error("Received empty content from LLM.")
                 raise ValueError("LLM returned empty content.")

            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                 logger.warning("LLM response was not valid JSON despite requesting JSON format. Attempting cleanup.")
                 if content.strip().startswith("```") and content.strip().endswith("```"):
                      cleaned_content = content.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                      try:
                           data = json.loads(cleaned_content)
                           logger.info("Successfully parsed JSON after cleanup.")
                      except json.JSONDecodeError as json_e_clean:
                           logger.error(f"Failed to parse LLM response as JSON even after cleanup: {json_e_clean}. Response: {content[:500]}...")
                           raise ValueError(f"LLM returned non-JSON data after cleanup attempt.")
                 else:
                      logger.error(f"Failed to parse LLM response as JSON and cleanup markers not found. Response: {content[:500]}...")
                      raise ValueError(f"LLM returned non-JSON data.")

            extracted_title = data.get("meeting_title")
            extracted_date_str = data.get("meeting_date_extracted")
            extracted_participants = data.get("participants_extracted", [])
            if not isinstance(extracted_participants, list):
                logger.warning(f"Participants field was not a list, defaulting to empty. Value: {extracted_participants}")
                extracted_participants = []
            if extracted_title is not None and not isinstance(extracted_title, str): extracted_title = str(extracted_title)

            parsed_meeting_date = self._parse_relative_date(extracted_date_str, today)

            meeting_details = {
                "title": extracted_title or f"Meeting Analysis {today.strftime('%Y%m%d_%H%M%S')}",
                "meeting_date": parsed_meeting_date or today,
                "participants": extracted_participants, # Keep as list
            }

            analysis_summary = data.get("summary")
            analysis_key_points = data.get("key_points", [])
            analysis_task = data.get("task")
            analysis_responsible = data.get("responsible")
            analysis_deadline_str = data.get("deadline")

            if not isinstance(analysis_key_points, list):
                 logger.warning(f"Key points field was not a list, defaulting to empty. Value: {analysis_key_points}")
                 analysis_key_points = []
            analysis_summary = str(analysis_summary) if analysis_summary is not None else None
            analysis_task = str(analysis_task) if analysis_task is not None else None
            analysis_responsible = str(analysis_responsible) if analysis_responsible is not None else None

            parsed_deadline = self._parse_relative_date(analysis_deadline_str, today)

            analysis_results = {
                "summary": analysis_summary,
                "key_points": analysis_key_points,
                "task": analysis_task,
                "responsible": analysis_responsible,
                "deadline": parsed_deadline,
            }

            return {
                "meeting_details": meeting_details,
                "analysis_results": analysis_results,
            }

        except json.JSONDecodeError as e:
             logged_content = content[:500] + "..." if 'content' in locals() else "Content unavailable"
             logger.error(f"JSON Decode Error analyzing transcript: {e}. Content was: {logged_content}", exc_info=True)
             raise ValueError(f"Failed to parse analysis result from LLM: {e}") from e
        except Exception as e:
            logger.error(f"Error during transcript analysis with model {self.model}: {e}", exc_info=True)
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