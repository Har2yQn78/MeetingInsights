import logging
import os
import numpy as np
from decouple import config, AutoConfig
from django.conf import settings
import mistralai
from typing import List, Union, Optional, Dict, Any

logger = logging.getLogger(__name__)

config_search_path = settings.BASE_DIR
decouple_config = AutoConfig(search_path=config_search_path)

class MistralService:
    def __init__(self):
        self.api_key = decouple_config("MISTRAL_API_KEY", default=None)
        self.embedding_model = settings.MISTRAL_EMBED_MODEL
        self.chat_model = settings.MISTRAL_CHAT_MODEL

        if not self.api_key:
            logger.error("MISTRAL_API_KEY not found in .env file or environment variables.")
            raise ValueError("MISTRAL_API_KEY not configured.")

        try:
            self.client = mistralai.Mistral(api_key=self.api_key)
            logger.info(f"Mistral client initialized. Embedding: '{self.embedding_model}', Chat: '{self.chat_model}'")
        except AttributeError:
             logger.error("Failed to find 'Mistral' class in the 'mistralai' library. Check installation/version (maybe try 'MistralClient'?).")
             raise ImportError("Could not find Mistral class in the installed mistralai library.")
        except Exception as e:
            logger.error(f"Failed to initialize Mistral client: {e}", exc_info=True)
            raise ConnectionError(f"Mistral client initialization failed: {e}") from e

    def get_embeddings(self, texts: Union[str, List[str]]) -> Union[np.ndarray, List[np.ndarray]]:
        is_single_text = False
        if isinstance(texts, str):
            texts = [texts]
            is_single_text = True
        elif not isinstance(texts, list):
            raise TypeError("Input 'texts' must be a string or a list of strings.")

        if not texts: return np.array([]) if is_single_text else []
        cleaned_texts = [str(t).strip() for t in texts]

        try:
            logger.debug(f"Requesting embeddings for {len(cleaned_texts)} text(s) using model {self.embedding_model}.")
            response = self.client.embeddings.create(model=self.embedding_model, inputs=cleaned_texts)
            if not response or not hasattr(response, 'data') or not response.data:
                 raise ValueError("Mistral API returned no embedding data or unexpected structure.")

            embeddings_list = [np.array(entry.embedding, dtype=np.float32) for entry in response.data]

            if len(embeddings_list) != len(cleaned_texts):
                logger.error(f"Mismatch count: requested texts ({len(cleaned_texts)}) vs received embeddings ({len(embeddings_list)}).")
                raise ValueError("Received unexpected number of embeddings from Mistral API.")

            logger.debug(f"Successfully received {len(embeddings_list)} embeddings.")
            return embeddings_list[0] if is_single_text else embeddings_list

        except ConnectionError as e:
             logger.error(f"Connection error during embedding: {e}", exc_info=True)
             raise
        except Exception as e:
            logger.error(f"Mistral API error or unexpected issue during embedding generation: {e}", exc_info=True)
            raise ValueError(f"Embedding generation failed: {e}") from e


    def get_query_embedding(self, text: str) -> np.ndarray:
        if not isinstance(text, str): raise TypeError("Query text must be a string.")
        return self.get_embeddings(text)
    def generate_response(self, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            logger.debug(f"Requesting chat completion using model {self.chat_model}.")
            chat_response = self.client.chat.complete(
                model=self.chat_model,
                messages=messages,
                temperature=temperature,
            )
            if not chat_response or not hasattr(chat_response, 'choices') or not chat_response.choices:
                raise ValueError("Mistral API returned no choices in chat response or unexpected structure.")

            response_content = chat_response.choices[0].message.content
            if response_content is None:
                 logger.warning("Mistral API returned None response content.")
                 return ""

            logger.debug("Successfully received chat completion.")
            return response_content
        except ConnectionError as e:
             logger.error(f"Connection error during chat generation: {e}", exc_info=True)
             raise
        except Exception as e:
            logger.error(f"Mistral API error or unexpected issue during chat generation: {e}", exc_info=True)
            raise ValueError(f"Chat generation failed: {e}") from e