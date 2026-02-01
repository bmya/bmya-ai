# -*- coding: utf-8 -*-
"""
Perplexity API Service for Odoo

Provides a service class to interact with Perplexity AI API,
following the same patterns as Odoo's LLMApiService.
"""
import json
import logging
import os
import requests
from typing import Dict, List, Optional, Any

from odoo import _
from odoo.api import Environment
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Perplexity models available
PERPLEXITY_MODELS = [
    ('sonar', 'Sonar (Online)'),
    ('sonar-pro', 'Sonar Pro (Online)'),
    ('sonar-reasoning', 'Sonar Reasoning'),
    ('sonar-reasoning-pro', 'Sonar Reasoning Pro'),
]


class PerplexityApiService:
    """Service class for Perplexity AI API interactions.

    This class provides methods to interact with Perplexity AI,
    specifically designed for web-grounded search and classification tasks.

    Example usage:
        service = PerplexityApiService(self.env)
        response = service.chat_completion(
            system_prompt="You are a helpful assistant.",
            user_prompt="What is the capital of France?",
            model="sonar"
        )
    """

    PERPLEXITY_BASE_URL = "https://api.perplexity.ai"
    DEFAULT_MODEL = "sonar"
    DEFAULT_TIMEOUT = 60

    def __init__(self, env: Environment) -> None:
        self.env = env
        self._api_key = None

    def _get_api_key(self) -> str:
        """Get the Perplexity API key from config or environment.

        Returns:
            str: The API key

        Raises:
            UserError: If no API key is configured
        """
        if self._api_key:
            return self._api_key

        # Try config parameter first
        api_key = self.env["ir.config_parameter"].sudo().get_param("ai.perplexity_key")

        # Fall back to environment variable
        if not api_key:
            api_key = os.getenv("ODOO_AI_PERPLEXITY_TOKEN")

        if not api_key:
            raise UserError(_("No Perplexity API key configured. Please set it in Settings > General Settings > AI."))

        self._api_key = api_key
        return api_key

    def _get_headers(self) -> Dict[str, str]:
        """Get the headers for API requests."""
        return {
            "Authorization": f"Bearer {self._get_api_key()}",
            "Content-Type": "application/json",
        }

    def chat_completion(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.2,
        max_tokens: int = 1500,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> Dict[str, Any]:
        """Send a chat completion request to Perplexity.

        Args:
            user_prompt: The user's message/query
            system_prompt: Optional system prompt to guide the model
            model: The Perplexity model to use (default: sonar)
            temperature: Randomness of the response (0-1)
            max_tokens: Maximum tokens in response
            timeout: Request timeout in seconds

        Returns:
            Dict with 'content' (str), 'citations' (list), and 'usage' (dict)

        Raises:
            UserError: If the API request fails
        """
        messages = []

        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })

        messages.append({
            "role": "user",
            "content": user_prompt
        })

        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            response = requests.post(
                f"{self.PERPLEXITY_BASE_URL}/chat/completions",
                headers=self._get_headers(),
                json=body,
                timeout=timeout,
            )
            response.raise_for_status()
            result = response.json()

            # Extract content from response
            content = ""
            if choices := result.get("choices", []):
                content = choices[0].get("message", {}).get("content", "")

            # Extract citations if available
            citations = result.get("citations", [])

            # Extract usage info
            usage = result.get("usage", {})

            return {
                "content": content,
                "citations": citations,
                "usage": usage,
                "model": result.get("model", model),
            }

        except requests.exceptions.Timeout:
            _logger.error("Perplexity API timeout after %ds", timeout)
            raise UserError(_("Perplexity API request timed out. Please try again."))

        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            if e.response is not None:
                try:
                    error_data = e.response.json()
                    error_msg = error_data.get("error", {}).get("message", str(e))
                except (json.JSONDecodeError, KeyError):
                    error_msg = e.response.text or str(e)

            _logger.error("Perplexity API error: %s", error_msg)
            raise UserError(_("Perplexity API error: %s") % error_msg)

    def classify(
        self,
        text: str,
        categories: List[str],
        context: Optional[str] = None,
        model: str = DEFAULT_MODEL,
    ) -> Dict[str, Any]:
        """Classify text into one of the given categories.

        Args:
            text: The text to classify
            categories: List of possible categories
            context: Optional context to help classification
            model: The Perplexity model to use

        Returns:
            Dict with 'category' (str) and 'confidence' (str)
        """
        categories_str = ", ".join(categories)

        system_prompt = f"""You are a text classifier. You must classify the given text into exactly one of these categories: {categories_str}.

Respond with ONLY the category name, nothing else. If uncertain, choose the most likely category."""

        user_prompt = text
        if context:
            user_prompt = f"Context: {context}\n\nText to classify: {text}"

        response = self.chat_completion(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            model=model,
            temperature=0.1,
            max_tokens=50,
        )

        # Parse the category from response
        content = response.get("content", "").strip().upper()

        # Find the best matching category
        matched_category = None
        for category in categories:
            if category.upper() in content:
                matched_category = category
                break

        return {
            "category": matched_category,
            "raw_response": content,
            "usage": response.get("usage", {}),
        }

    def research(
        self,
        query: str,
        focus: Optional[str] = None,
        model: str = "sonar-pro",
        max_tokens: int = 2000,
    ) -> Dict[str, Any]:
        """Perform web research on a topic.

        Uses Perplexity's web-grounded search to find current information.

        Args:
            query: The research query
            focus: Optional focus area for the research
            model: Model to use (sonar-pro recommended for research)
            max_tokens: Maximum response tokens

        Returns:
            Dict with 'content', 'citations', and structured data if available
        """
        system_prompt = """You are a professional business researcher.
Your task is to find accurate, verifiable information about companies and contacts.
Always cite your sources and distinguish between confirmed facts and inferences.
If you cannot find reliable information, say so clearly."""

        if focus:
            query = f"Focus on {focus}:\n\n{query}"

        return self.chat_completion(
            user_prompt=query,
            system_prompt=system_prompt,
            model=model,
            temperature=0.1,
            max_tokens=max_tokens,
            timeout=90,  # Research queries may take longer
        )

    def is_available(self) -> bool:
        """Check if Perplexity API is available and configured.

        Returns:
            bool: True if API key is configured
        """
        try:
            self._get_api_key()
            return True
        except UserError:
            return False
