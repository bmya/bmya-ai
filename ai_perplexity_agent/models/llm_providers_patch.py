"""Patch to register Perplexity as an AI provider in Odoo's PROVIDERS list."""
import logging

from odoo.addons.ai.utils.llm_providers import Provider, PROVIDERS

_logger = logging.getLogger(__name__)

PERPLEXITY_PROVIDER = Provider(
    name="perplexity",
    display_name="Perplexity",
    # Perplexity has no embedding model; fallback to OpenAI's
    embedding_model="text-embedding-3-small",
    embedding_config={
        "max_batch_size": 2048,
        "max_tokens_per_request": 200000,
    },
    # Sonar Chat API models: https://docs.perplexity.ai/docs/getting-started/models
    # All models have built-in web search. No function calling support.
    llms=[
        ("perplexity/sonar", "Perplexity Sonar (Web Search)"),
        ("perplexity/sonar-pro", "Perplexity Sonar Pro (Deep Research)"),
        ("perplexity/sonar-reasoning-pro", "Perplexity Sonar Reasoning Pro"),
    ],
)


def _register_provider():
    """Append Perplexity provider to the PROVIDERS list."""
    if any(p.name == "perplexity" for p in PROVIDERS):
        return
    PROVIDERS.append(PERPLEXITY_PROVIDER)
    _logger.info("Perplexity provider registered in AI PROVIDERS list")


def _unregister_provider():
    """Remove Perplexity provider from the PROVIDERS list."""
    PROVIDERS[:] = [p for p in PROVIDERS if p.name != "perplexity"]
    _logger.info("Perplexity provider removed from AI PROVIDERS list")


# Register on module import (covers server restart)
_register_provider()


def uninstall_hook(env):
    """Called on module uninstall."""
    _unregister_provider()
