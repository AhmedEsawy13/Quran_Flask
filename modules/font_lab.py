"""Font Lab — interactive OpenType feature playground for Quran fonts.

Editor-gated (ENABLE_EDITOR / editor blueprint). No login required.
"""
from core.blueprints import editor_bp
from core.loader import IS_SERVERLESS as _IS_SERVERLESS
from flask import render_template


@editor_bp.route('/font-lab')
def font_lab_page():
    return render_template(
        'font_lab.html',
        enable_vercel_analytics=_IS_SERVERLESS,
    )
