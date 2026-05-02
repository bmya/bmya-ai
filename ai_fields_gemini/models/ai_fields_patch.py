"""Patch ai_fields to support Google Gemini as an alternative to OpenAI.

Odoo's ai_fields module is hardcoded to use OpenAI for AI-powered field
filling. This patch detects the available provider (OpenAI or Google) and
adjusts the model and web_grounding flag accordingly.

Gemini supports structured output (JSON schema) but cannot combine it with
web_grounding (Odoo raises NotImplementedError). Since schema is what matters
for field filling, we disable web_grounding when using Gemini.
"""
import logging
import os

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.ai.utils.llm_api_service import LLMApiService
from odoo.addons.ai_fields import tools as ai_fields_tools
from odoo.addons.ai_fields.models.ir_model_fields import IrModelFields

_logger = logging.getLogger(__name__)

_PROVIDER_CONFIG = {
    "openai": {
        "config_key": "ai.openai_key",
        "env_var": "ODOO_AI_CHATGPT_TOKEN",
        "model": "gpt-4.1",
        "web_grounding": True,
    },
    "google": {
        "config_key": "ai.google_key",
        "env_var": "ODOO_AI_GEMINI_TOKEN",
        "model": "gemini-2.5-flash",
        "web_grounding": False,
    },
}


def _detect_provider(env):
    """Detect the first available AI provider with a configured API key.

    Returns (provider_name, model, web_grounding) or None.
    """
    for provider_name, config in _PROVIDER_CONFIG.items():
        key = (
            env["ir.config_parameter"].sudo().get_param(config["config_key"])
            or os.getenv(config["env_var"])
        )
        if key:
            return provider_name, config["model"], config["web_grounding"]
    return None


# --- Patch get_ai_value (tools.py) ---
# This is the core function that builds the schema, calls LLMApiService,
# and parses the response. We patch it to use the detected provider.

_original_get_ai_value = ai_fields_tools.get_ai_value


def _patched_get_ai_value(record, field_type, user_prompt, context_fields, allowed_values):
    """Replace hardcoded OpenAI with auto-detected provider."""
    from odoo.addons.ai_fields.tools import (
        AI_FIELDS_INSTRUCTIONS, UnresolvedQuery, parse_ai_response,
    )
    import json
    import pytz
    import requests
    from datetime import datetime

    detected = _detect_provider(record.env)
    if not detected:
        raise UserError(_(
            "No AI provider configured. To use AI Fields, configure an API "
            "key for OpenAI or Google Gemini in Settings > AI."
        ))
    provider, model, web_grounding = detected

    if field_type in ('many2many', 'many2one', 'selection', 'tags') and not allowed_values:
        raise UnresolvedQuery(record.env._("No allowed values are provided in the prompt."))

    record_context, files = record._get_ai_context(context_fields)
    llm_api = LLMApiService(record.env, provider)

    # Build field_schema (same logic as original)
    if field_type == 'boolean':
        field_schema = {'type': 'boolean'}
    elif field_type == 'char':
        field_schema = {
            'type': 'string',
            'description': 'A short, concise string, without any Markdown formatting.',
        }
    elif field_type == 'date':
        field_schema = {
            'type': ['string', 'null'],
            'format': 'date',
            'description': 'A date (year, month and day should be correct), or null to leave empty',
        }
    elif field_type == 'datetime':
        field_schema = {
            'type': ['string', 'null'],
            'format': 'date-time',
            'description': 'A datetime (year, month and day should be correct), including the correct timezone or null to leave empty',
        }
    elif field_type == 'integer':
        field_schema = {
            'type': 'integer',
            'description': "A whole number. If a number is expressed in words (e.g. '6.67 billion'), it must be converted into its full numeric form (e.g. '6670000000')",
        }
    elif field_type in ('float', 'monetary'):
        field_schema = {'type': 'number'}
    elif field_type == 'html':
        field_schema = {
            'type': 'string',
            'description': 'A well-structured Markdown (it may contain tables). It will be converted to HTML after generation',
        }
    elif field_type == 'text':
        field_schema = {
            'type': 'string',
            'description': 'A few sentences, without any Markdown formatting',
        }
    elif field_type == 'many2many':
        field_schema = {
            'type': 'array',
            'items': {'type': 'integer', 'enum': list(allowed_values)},
            'description': 'The list of IDs of records to select. Leave empty to leave the field empty',
        }
    elif field_type == 'many2one':
        field_schema = {
            'type': ['integer', 'null'],
            'enum': list(allowed_values) + [None],
            'description': 'The ID of the record to select. null to leave the field empty if no value matches the user query',
        }
    elif field_type == 'selection':
        field_schema = {
            'type': ['string', 'null'],
            'enum': list(allowed_values) + [None],
            'description': 'Key of the value to select. null to leave the field empty',
        }
    elif field_type == 'tags':
        field_schema = {
            'type': 'array',
            'items': {'type': 'string', 'enum': list(allowed_values)},
            'description': 'List of keys of the tags to select. Leave empty to leave the field empty',
        }
    else:
        field_schema = {'type': 'text'}

    schema = {
        'type': 'object',
        'properties': {
            'value': field_schema,
            'could_not_resolve': {
                'type': 'boolean',
                'description': 'True if the model could not confidently determine a value due to missing information, ambiguity, or unknown references in the input.',
            },
            'unresolved_cause': {
                'type': ['string', 'null'],
                'description': 'Short explanation of what is missing or why no value could be generated. Required if could_not_resolve is true.',
            },
        },
        'required': ['value', 'could_not_resolve', 'unresolved_cause'],
        'additionalProperties': False,
    }

    instructions = f"{AI_FIELDS_INSTRUCTIONS}\n# Context"
    if allowed_values:
        instructions += f"\n## Allowed Values\n{json.dumps(allowed_values)}"
    instructions += f"\n The current date is {datetime.now(pytz.utc).astimezone().replace(second=0, microsecond=0).isoformat()}"

    if record_context != '{}':
        user_prompt += f"\n# Context Dict\n{record_context}"
        user_prompt += f"\nThe current record is {{'model': {record._name}, 'id': {record.id}}}"

    try:
        response, *__ = llm_api._request_llm(
            llm_model=model,
            system_prompts=[instructions],
            user_prompts=[user_prompt],
            files=files,
            schema=schema,
            web_grounding=web_grounding,
        )
    except requests.exceptions.Timeout:
        raise UserError(record.env._("Oops, the request timed out."))
    except requests.exceptions.ConnectionError:
        raise UserError(record.env._("Oops, the connection failed."))

    if not response:
        raise UserError(record.env._("Oops, an unexpected error occurred."))

    try:
        response = json.loads(response[0], strict=False)
    except json.JSONDecodeError:
        raise UserError(record.env._("Oops, the response could not be processed."))
    if response.get('could_not_resolve'):
        raise UnresolvedQuery(response.get('unresolved_cause'))

    return parse_ai_response(
        response.get('value'),
        field_type,
        allowed_values,
    )


ai_fields_tools.get_ai_value = _patched_get_ai_value


# --- Patch _cron_fill_ai_fields (ir_model_fields.py) ---
# The cron validates the OpenAI key before processing. We replace
# that validation with our provider detection.

_original_cron = IrModelFields._cron_fill_ai_fields


def _patched_cron_fill_ai_fields(self, batch_size=10):
    """Check any available provider, not just OpenAI."""
    import datetime as dt

    detected = _detect_provider(self.env)
    if not detected:
        _logger.info("AI Fields cron skipped, no AI provider key configured")
        return

    provider, model, web_grounding = detected
    _logger.info("AI Fields cron using provider '%s' with model '%s'", provider, model)

    # Replicate the original cron body (lines 78-112 of ir_model_fields.py)
    # but without the OpenAI key check that already passed above.
    from odoo.tools import OrderedSet, SQL
    import ast

    fields = self.search([
        '|',
            '&', '&', ('ai', '=', True), ('system_prompt', '!=', False), ('ttype', 'in', ('char', 'text', 'html')),
            '&', ('ttype', '=', 'properties_definition'), ('store', '=', True),
    ], order='id')
    remaining_fields = len(fields)

    total_done = 0
    total_remaining = 0
    for field in fields:
        done, remaining, has_time_left = (
            self._ai_fill_records_with_empty_property(field, batch_size, remaining_fields)
            if field.ttype == 'properties_definition' else
            self._ai_fill_records_with_empty_field(field, batch_size, remaining_fields)
        )
        total_done += done
        total_remaining += remaining
        if not remaining:
            remaining_fields -= 1
        if not has_time_left:
            break

    if not remaining_fields:
        self.env['ir.cron']._commit_progress(remaining=0)
    else:
        if not total_done:
            self.env['ir.cron']._commit_progress(remaining=0)
            _logger.info('AI Fields cron rescheduled soon because all records were locked')
            self.env.ref('ai_fields.ir_cron_fill_ai_fields')._trigger(
                self.env.cr.now() + dt.timedelta(minutes=1),
            )
        elif total_remaining:
            _logger.info('AI Fields cron skipped %s records', total_remaining)


IrModelFields._cron_fill_ai_fields = _patched_cron_fill_ai_fields

_logger.info("ai_fields_gemini: patches applied (get_ai_value, _cron_fill_ai_fields)")
