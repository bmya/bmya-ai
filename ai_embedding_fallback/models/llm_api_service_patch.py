"""Patch LLMApiService to auto-detect embedding provider.

Providers like Perplexity and Anthropic don't have embedding APIs.
This patch detects which provider with embedding support has an API key
configured and delegates embedding requests to it.
"""
import logging
import os

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.ai.utils.llm_api_service import LLMApiService
from odoo.addons.ai.utils.llm_providers import PROVIDERS

_logger = logging.getLogger(__name__)

# Providers known to NOT have embedding APIs
_PROVIDERS_WITHOUT_EMBEDDINGS = {"perplexity", "anthropic"}

# API key config per provider (mirrors enterprise _get_api_token)
_PROVIDER_KEY_CONFIG = {
    "openai": ("ai.openai_key", "ODOO_AI_CHATGPT_TOKEN"),
    "google": ("ai.google_key", "ODOO_AI_GEMINI_TOKEN"),
}

_original_get_embedding = LLMApiService.get_embedding


def _find_embedding_provider(env):
    """Find first available provider with embedding API and configured key."""
    for provider in PROVIDERS:
        if provider.name in _PROVIDERS_WITHOUT_EMBEDDINGS:
            continue
        config = _PROVIDER_KEY_CONFIG.get(provider.name)
        if not config:
            continue
        config_key, env_var = config
        if env["ir.config_parameter"].sudo().get_param(config_key) or os.getenv(env_var):
            return provider
    return None


def _patched_get_embedding(self, input, dimensions, model='text-embedding-3-small',
                           encoding_format=None, user=None):
    """Auto-detect embedding provider for providers without embedding API."""
    if self.provider in _PROVIDERS_WITHOUT_EMBEDDINGS:
        fallback = _find_embedding_provider(self.env)
        if not fallback:
            raise UserError(_(
                "The selected AI provider does not have an embedding API. "
                "To use document sources (RAG), configure an API key for "
                "a provider with embedding support (e.g., OpenAI or Google) "
                "in Settings > AI."
            ))
        _logger.info(
            "Provider '%s' has no embedding API, using '%s' for embeddings",
            self.provider, fallback.name,
        )
        fallback_service = LLMApiService(env=self.env, provider=fallback.name)
        return fallback_service.get_embedding(
            input=input, dimensions=dimensions,
            model=fallback.embedding_model,
            encoding_format=encoding_format, user=user,
        )
    return _original_get_embedding(self, input, dimensions, model, encoding_format, user)


# Apply patch
LLMApiService.get_embedding = _patched_get_embedding
_logger.info("Embedding fallback patch applied to LLMApiService")
