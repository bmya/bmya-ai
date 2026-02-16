"""Patch LLMApiService to support Perplexity as an AI provider.

Uses the Sonar Chat API (/chat/completions) which provides:
- Built-in web search (native to all Sonar models)
- sonar, sonar-pro, sonar-reasoning-pro models
- Proven reliability (same API used by crm_enrichment)

Limitation: No function calling support. Agents with Perplexity
models work as conversational/research assistants without tools.
"""
import json
import logging
import os
import re

import requests

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.ai.utils.llm_api_service import LLMApiService
from odoo.addons.ai.utils.ai_logging import api_call_logging

_logger = logging.getLogger(__name__)

PERPLEXITY_BASE_URL = "https://api.perplexity.ai"
PERPLEXITY_TIMEOUT = 120

# Store original methods before patching
_original_init = LLMApiService.__init__
_original_get_api_token = LLMApiService._get_api_token
_original_request_llm = LLMApiService._request_llm
_original_build_tool_call_response = LLMApiService._build_tool_call_response


def _patched_init(self, env, provider='openai'):
    """Support perplexity provider without hitting NotImplementedError."""
    if provider == 'perplexity':
        self.provider = provider
        self.base_url = PERPLEXITY_BASE_URL
        self.env = env
    else:
        _original_init(self, env, provider)


def _patched_get_api_token(self):
    """Add perplexity API key lookup."""
    if self.provider == 'perplexity':
        api_key = (
            self.env["ir.config_parameter"].sudo().get_param("ai.perplexity_key")
            or os.getenv("ODOO_AI_PERPLEXITY_TOKEN")
        )
        if api_key:
            return api_key
        raise UserError(_("No API key set for provider 'perplexity'"))
    return _original_get_api_token(self)


def _patched_request_llm(self, *args, **kwargs):
    """Dispatch perplexity requests to dedicated handler."""
    if self.provider == 'perplexity':
        return self._request_llm_perplexity(*args, **kwargs)
    return _original_request_llm(self, *args, **kwargs)


def _request_llm_perplexity(
    self, llm_model, system_prompts, user_prompts, tools=None,
    files=None, schema=None, temperature=0.2, inputs=(), web_grounding=False
):
    """Send request via Perplexity Sonar Chat API (/chat/completions).

    Uses the standard chat completions format with native web search.
    All Sonar models have built-in web grounding — no explicit tool needed.

    Note: Function calling (tools) is not supported by the Sonar Chat API.
    Tools parameter is ignored; agents using Perplexity work as
    conversational/research assistants.
    """
    # Separate Odoo internal context from actual user conversation.
    # Odoo sends inputs like:
    #   [0] {role:user, content:"<session_info_context>...Mitchell Admin..."} (internal)
    #   [1..N-1] chat history (user/assistant alternating)
    #   [N] {role:user, content:"actual user question"}
    # We move XML/internal context to system prompt so it doesn't pollute
    # Perplexity's web search queries.
    extra_system_parts = []
    raw_messages = []

    for item in (inputs or []):
        if "role" not in item or "content" not in item:
            continue
        content = item["content"]
        if isinstance(content, str):
            content = content.strip()
        if not content:
            continue
        # Detect Odoo session_info_context (XML) and move to system
        if item["role"] == "user" and "<session_info_context>" in content:
            extra_system_parts.append(content)
        else:
            raw_messages.append({
                "role": item["role"],
                "content": content,
            })

    # Direct user prompts (may be empty in agent chat flow)
    for prompt in (user_prompts or []):
        if prompt and str(prompt).strip():
            raw_messages.append({
                "role": "user",
                "content": str(prompt).strip(),
            })

    # Build system message: original system_prompts + extracted Odoo context
    # + HTML output instruction for consistent rendering in Odoo's chatter
    all_system_parts = list(system_prompts or []) + extra_system_parts
    all_system_parts.append(
        "IMPORTANT: Always deliver your response in well-structured HTML format, "
        "visually organized and pleasant to read, for every section of the response. "
        "Use appropriate HTML tags: <h2>/<h3> for headings, <p> for paragraphs, "
        "<ul>/<li> for lists, <table> for tabular data, <b> for emphasis, "
        "<a href> for links. Never use markdown syntax."
    )
    messages = []
    if all_system_parts:
        messages.append({
            "role": "system",
            "content": "\n\n".join(all_system_parts),
        })

    # Perplexity Chat API requires strict alternation: user/assistant
    # Merge consecutive messages with the same role
    for msg in raw_messages:
        if messages and messages[-1]["role"] == msg["role"]:
            messages[-1]["content"] += "\n\n" + msg["content"]
        else:
            messages.append(dict(msg))

    # Ensure the last message is from the user (required by Perplexity)
    if not messages or messages[-1]["role"] != "user":
        messages.append({"role": "user", "content": "..."})

    # Strip the "perplexity/" prefix for the Chat API
    # Agent API uses "perplexity/sonar", Chat API uses "sonar"
    api_model = llm_model
    if api_model.startswith("perplexity/"):
        api_model = api_model[len("perplexity/"):]

    body = {
        "model": api_model,
        "messages": messages,
        "temperature": temperature,
        # Force web search with thorough query depth
        "web_search_options": {
            "search_context_size": "high",
        },
    }

    _logger.info(
        "[Perplexity] Chat API request model=%s, messages=%d, roles=%s",
        api_model, len(messages),
        [m["role"] for m in messages],
    )

    # Make the request directly (not through _request_llm_openai_helper)
    with api_call_logging(messages, tools) as record_response:
        try:
            response = requests.post(
                f"{PERPLEXITY_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._get_api_token()}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=PERPLEXITY_TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()

            # Extract content and citations from chat completions response
            content = ""
            citations = []
            if choices := result.get("choices", []):
                choice = choices[0]
                content = choice.get("message", {}).get("content", "")
                citations = choice.get("citations", [])

            # Also check top-level citations (API format varies)
            if not citations:
                citations = result.get("citations", [])

            _logger.info(
                "[Perplexity] Response keys=%s, choice keys=%s, citations=%s",
                list(result.keys()),
                list(choices[0].keys()) if choices else [],
                citations,
            )

            # Process Perplexity citations: the API returns inline [1][2]
            # references in content, and a citations list with URLs.
            # We replace [N] with clickable links and append a Sources footer.
            # Content goes through markdown() then html_sanitize() in Odoo,
            # so we use markdown link format for the footer and HTML for inline.
            if content and citations:
                citation_urls = {}
                for i, cite in enumerate(citations, 1):
                    if isinstance(cite, dict):
                        url = cite.get("url", "")
                    elif isinstance(cite, str):
                        url = cite
                    else:
                        continue
                    if url:
                        citation_urls[i] = url

                # Replace inline [N] with HTML links (preserved by markdown2)
                for num, url in sorted(citation_urls.items(), reverse=True):
                    content = content.replace(
                        f'[{num}]',
                        f'<a href="{url}" target="_blank">[{num}]</a>',
                    )

                # Append Sources footer as HTML (content is HTML per prompt)
                if citation_urls:
                    content += (
                        '<hr><p><b>Sources:</b></p><ul>'
                    )
                    for num, url in citation_urls.items():
                        domain = url.split("//")[-1].split("/")[0]
                        content += (
                            f'<li><a href="{url}" target="_blank">'
                            f'[{num}] {domain}</a></li>'
                        )
                    content += '</ul>'

            # Track token usage
            request_token_usage = {}
            if usage := result.get("usage"):
                request_token_usage["input_tokens"] = usage.get("prompt_tokens", 0)
                request_token_usage["cached_tokens"] = 0
                request_token_usage["output_tokens"] = usage.get("completion_tokens", 0)

            if record_response:
                record_response([], [content] if content else [], request_token_usage)

            # Return format expected by Odoo: (responses, tool_calls, next_inputs)
            # No tool calls since Chat API doesn't support function calling
            return [content] if content else [], [], list(inputs or ())

        except requests.exceptions.Timeout:
            _logger.error("Perplexity API timeout after %ds", PERPLEXITY_TIMEOUT)
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


def _patched_build_tool_call_response(self, tool_call_id, return_value):
    """Perplexity doesn't support tools, but handle gracefully."""
    if self.provider == 'perplexity':
        return {
            "type": "function_call_output",
            "call_id": tool_call_id,
            "output": str(return_value),
        }
    return _original_build_tool_call_response(self, tool_call_id, return_value)


# Apply patches
LLMApiService.__init__ = _patched_init
LLMApiService._get_api_token = _patched_get_api_token
LLMApiService._request_llm = _patched_request_llm
LLMApiService._request_llm_perplexity = _request_llm_perplexity
LLMApiService._build_tool_call_response = _patched_build_tool_call_response
_logger.info("Perplexity Sonar Chat API patches applied to LLMApiService")
