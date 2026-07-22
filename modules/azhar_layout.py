"""Azhar layout — legacy aliases for Layout Studio edition `azhar`.

Prefer /layout-studio/azhar and /api/layout-studio/azhar/*. These routes stay
so bookmarks and mushaf-editor links keep working.
"""
from __future__ import annotations

from core.blueprints import editor_bp
from modules.layout_editions import AZHAR, default_edition
from modules.layout_studio import (
    _cascade_from as _studio_cascade,
    layout_studio_line_break,
    layout_studio_merge_line,
    layout_studio_page,
    layout_studio_progress,
    layout_studio_undo,
    layout_studio_undo_status,
    render_studio,
)

# Re-export constants/tests helpers expected by older imports.
FATIHA_PAGE = AZHAR.closed_page.page if AZHAR.closed_page else 2
FATIHA_AYAH_FIRST = AZHAR.closed_page.ayah_first if AZHAR.closed_page else 8
FATIHA_AYAH_LAST = AZHAR.closed_page.ayah_last if AZHAR.closed_page else 38
BAQARAH_FIRST_WORD = (
    AZHAR.closed_page.next_page_first_word if AZHAR.closed_page else 45
)


def _cascade_from(lines, start_idx, head_words, text_map, universe=None, page_scope=None):
    """Test/compat wrapper around the studio cascade for edition azhar."""
    return _studio_cascade(
        AZHAR, lines, start_idx, head_words, text_map,
        universe=universe, page_scope=page_scope,
    )


@editor_bp.route('/azhar-layout')
def azhar_layout_page():
    # Keep serving the studio UI at the old URL (no redirect flash).
    return render_studio(default_edition())


@editor_bp.route('/api/azhar-layout/page/<int:page_number>', methods=['GET'])
def get_azhar_layout_editor_page(page_number):
    return layout_studio_page('azhar', page_number)


@editor_bp.route('/api/azhar-layout/line-break', methods=['POST'])
def azhar_layout_line_break():
    return layout_studio_line_break('azhar')


@editor_bp.route('/api/azhar-layout/merge-line', methods=['POST'])
def azhar_layout_merge_line():
    return layout_studio_merge_line('azhar')


@editor_bp.route('/api/azhar-layout/undo', methods=['POST'])
def azhar_layout_undo():
    return layout_studio_undo('azhar')


@editor_bp.route('/api/azhar-layout/undo-status', methods=['GET'])
def azhar_layout_undo_status():
    return layout_studio_undo_status('azhar')


@editor_bp.route('/api/azhar-layout/progress', methods=['GET', 'POST'])
def azhar_layout_progress():
    return layout_studio_progress('azhar')
