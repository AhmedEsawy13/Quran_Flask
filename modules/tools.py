"""/tools — one page listing the editor's internal tools (editor feature only).

Each entry says what the tool is for and whether it can run on this server:
some read files that exist only on the machine that produced them (the book
audits under artifacts/, the CV page scans under data/cv/pages).
"""
from __future__ import annotations

from flask import render_template

from core import supabase_editor as sb
from core.blueprints import editor_bp
from modules.layout_editions import list_editions


def _book_audits() -> list[str]:
    from modules.audit_review import REVIEW_EDITIONS
    from pipeline.cv_waqf.config import ARTIFACTS_ROOT, EDITIONS
    return [name for name in sorted(REVIEW_EDITIONS)
            if name in EDITIONS and (ARTIFACTS_ROOT / f'{EDITIONS[name].id}-audit' / 'queue.json').is_file()]


def _cv_pages_cached() -> bool:
    from pipeline.cv_waqf.config import ROOT
    pages = ROOT / 'data' / 'cv' / 'pages'
    return pages.is_dir() and any(pages.iterdir())


def tool_groups() -> list[dict]:
    cloud = sb.is_configured()
    audits = _book_audits()
    cloud_note = None if cloud else 'غير متصل بالسحابة على هذا الخادم: التعديلات لا تُحفظ'
    return [
        {'title': 'مراجعة الوقف', 'icon': 'fa-pen-nib', 'tools': [
            {'href': '/mushaf-editor', 'name': 'محرّر الوقف',
             'desc': 'ضبط علامات الوقف في مصاحف قطر والكويت والبحرين بالنقر على الكلمة، ثم النشر.',
             'note': cloud_note},
            {'href': '/mushaf-editor/book-audit', 'name': 'مراجعة الفحص',
             'desc': 'بطاقات فحص الصور لكل مصحف: اعتمد الصورة أو القاعدة، ويُحفظ القرار في السحابة. '
                     'الشمرلي والمدينة القديم للمراجعة فقط: يُسجَّل القرار ويُطبَّق على القاعدة لاحقًا.',
             'links': [{'href': f'/mushaf-editor/book-audit?edition={name}', 'label': name} for name in audits],
             'note': None if audits else 'لا يوجد فحص على هذا الخادم — يعمل حيث شُغّل الفحص (جهازك)'},
            {'href': '/waqf-mark-review', 'name': 'مراجعة علامات الشمرلي',
             'desc': 'قائمة مراجعة صفحة بصفحة لعلامات مصحف الشمرلي، مع نسخ للطباعة.'},
            {'href': '/azhar-waqf-review', 'name': 'مراجعة علامات الأزهر',
             'desc': 'مراجعة وقوف مصحف الأزهر سورةً سورة.'},
            {'href': '/cv-waqf', 'name': 'تسمية علامات الوقف',
             'desc': 'تسمية علامات الوقف على صور الصفحات لتدريب نموذج الكشف.',
             'note': None if _cv_pages_cached() else 'صور الصفحات غير موجودة على هذا الخادم'},
        ]},
        {'title': 'التخطيط والخط', 'icon': 'fa-table-cells', 'tools': [
            {'href': '/layout-studio', 'name': 'استوديو التخطيط',
             'desc': 'ضبط أسطر الصفحات وفواصلها ومواضع العناوين لكل مصحف.',
             'links': [{'href': f'/layout-studio/{e.id}', 'label': e.name_ar} for e in list_editions()]},
            {'href': '/font-lab', 'name': 'مختبر الخط',
             'desc': 'تجربة خطوط المصاحف وخصائصها على نصوص مختارة.'},
        ]},
        {'title': 'الكتب والنص', 'icon': 'fa-book-open', 'tools': [
            {'href': '/classical-review', 'name': 'مراجعة كتب الوقف',
             'desc': 'مراجعة ما استُخرج من كتب الوقف (المكتفى وغيره) ومطابقته بالمواضع.'},
            {'href': '/tawjih-review', 'name': 'مراجعة التوجيه',
             'desc': 'مراجعة توجيهات د. أحمد قبل اعتمادها.'},
            {'href': '/quran-integrity-review', 'name': 'سلامة النص القرآني',
             'desc': 'تقرير فحص النص والكلمات في قواعد البيانات.'},
        ]},
        {'title': 'المتابعة', 'icon': 'fa-clock-rotate-left', 'tools': [
            {'href': '/activity', 'name': 'سجل التعديلات ولوحة المحرّرين',
             'desc': 'ما أنجزه كل محرّر (علامات، قرارات، تخطيط، نشر) خلال أسبوع أو شهر، ثم السجل الكامل لكل تعديل.',
             'note': cloud_note},
        ]},
    ]


@editor_bp.route('/tools')
def tools_page():
    return render_template('tools.html', groups=tool_groups(), cloud=sb.is_configured())
