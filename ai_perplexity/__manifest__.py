{
    'name': 'AI Perplexity Provider',
    'version': '19.0.1.0.0',
    'category': 'Hidden',
    'summary': 'Adds Perplexity AI as a provider for Odoo AI features',
    'description': """
AI Perplexity Provider
======================

Extends the Odoo Enterprise AI module to support Perplexity AI as an additional provider.

Features:
- Perplexity API integration (Sonar model).
- Web search capabilities with real-time data.
- Compatible with existing AI infrastructure.

Configuration:
- Set your Perplexity API key in Settings > General Settings > AI
- Or use environment variable: ODOO_AI_PERPLEXITY_TOKEN
    """,
    'author': 'BMyA - Blanco Martín y Asociados',
    'website': 'https://www.bmya.cl',
    'license': 'OPL-1',
    'depends': ['ai'],
    'data': [
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
