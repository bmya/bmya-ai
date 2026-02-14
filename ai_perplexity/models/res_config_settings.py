from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    perplexity_key_enabled = fields.Boolean(
        string="Enable Perplexity API",
        compute='_compute_perplexity_key_enabled',
        readonly=False,
        groups='base.group_system',
    )
    perplexity_key = fields.Char(
        string="Perplexity API key",
        config_parameter='ai.perplexity_key',
        readonly=False,
        groups='base.group_system',
        help="API key for Perplexity AI. Get one at https://www.perplexity.ai/settings/api"
    )
    def _compute_perplexity_key_enabled(self):
        for record in self:
            record.perplexity_key_enabled = bool(record.perplexity_key)
