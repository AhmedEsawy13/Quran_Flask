/* ═══════════════════════════════════════════════════════════════════
   Font Lab catalog — curated Quran fonts + OpenType feature tags.

   How to add a font:
     1. Ensure @font-face exists (styles.css or font_lab.css).
     2. Push a FONTS entry with family + supportedTags (+ featureMax).
     3. Optionally add SAMPLES that stress its unique tags.

   How to add a feature:
     1. Add to FEATURES (tag, labelAr, group, noteAr, max?).
        max>1 → stepped alternate selector ('cv01' N).
        max=1/omit → on/off toggle ('tag' 1).
     2. Include the tag in each font's supportedTags.
   ═══════════════════════════════════════════════════════════════════ */
(function (global) {
    'use strict';

    const GROUPS = [
        { id: 'justify', labelAr: 'تطويل / كشيدة (تبرير)' },
        { id: 'variants', labelAr: 'بدائل حرفية — كاف / ميم / أشكال' },
        { id: 'liga', labelAr: 'ربط وتشكيل عام' },
        { id: 'quran', labelAr: 'علامات قرآنية / رموز' },
    ];

    /** Shared feature definitions (Arabic labels for the lab UI). */
    const FEATURES = [
        {
            tag: 'jalt', group: 'justify', max: 1,
            labelAr: 'كشيدة تبرير (jalt)',
            noteAr: 'إطالة عامة للسطر — ليست «كاف زنادية» بعينها، لكنها تمدّ الوصلات',
        },
        { tag: 'jt01', group: 'justify', max: 1, labelAr: 'كشيدة منحنية jt01', noteAr: 'الشامية' },
        { tag: 'jt02', group: 'justify', max: 1, labelAr: 'كشيدة منحنية jt02', noteAr: '' },
        { tag: 'jt03', group: 'justify', max: 1, labelAr: 'كشيدة منحنية jt03', noteAr: '' },
        { tag: 'jt04', group: 'justify', max: 1, labelAr: 'كشيدة منحنية jt04', noteAr: '' },
        { tag: 'jt05', group: 'justify', max: 1, labelAr: 'كشيدة منحنية jt05', noteAr: '' },
        { tag: 'kt01', group: 'justify', max: 1, labelAr: 'كشيدة kt01', noteAr: 'الشامية' },
        { tag: 'kt02', group: 'justify', max: 1, labelAr: 'كشيدة kt02', noteAr: '' },
        { tag: 'kt03', group: 'justify', max: 1, labelAr: 'كشيدة kt03', noteAr: '' },
        { tag: 'kt04', group: 'justify', max: 1, labelAr: 'كشيدة kt04', noteAr: '' },
        { tag: 'kt05', group: 'justify', max: 1, labelAr: 'كشيدة kt05', noteAr: '' },
        { tag: 'dc01', group: 'justify', max: 1, labelAr: 'تضييق/تمديد dc01', noteAr: 'الشامية' },
        { tag: 'dc02', group: 'justify', max: 1, labelAr: 'تضييق/تمديد dc02', noteAr: '' },
        { tag: 'dc03', group: 'justify', max: 1, labelAr: 'تضييق/تمديد dc03', noteAr: '' },

        {
            tag: 'cv01', group: 'variants', max: 12,
            labelAr: 'كاف / اتصالات — cv01',
            noteAr: 'أقرب ما عندنا لـ«كاف زنادية/ممتدة»: بدائل شكل الكاف والوصلات. جرّب 1…12 على حكيم',
        },
        {
            tag: 'cv02', group: 'variants', max: 12,
            labelAr: 'ميم / تمديد عمودي — cv02',
            noteAr: 'بدائل ميم وكشيدة عمودية/شكلية. واضح جداً في المدينة القديمة على ميم حكيم',
        },
        {
            tag: 'cv03', group: 'variants', max: 1,
            labelAr: 'أشكال سياقية مبسّطة — cv03',
            noteAr: 'غالباً تبديل شكل واحد (مثل كاف.init → كاف.init.ii في المدينة القديمة)',
        },
        {
            tag: 'cv04', group: 'variants', max: 5,
            labelAr: 'ضغط/توسيع خفيف — cv04',
            noteAr: 'المدينة القديمة فقط — درجات سالبة/موجبة حول الكاف والميم',
        },
        { tag: 'cv10', group: 'variants', max: 1, labelAr: 'بديل تبرير cv10', noteAr: 'سلم تبرير إضافي' },
        { tag: 'cv11', group: 'variants', max: 1, labelAr: 'بديل تبرير cv11', noteAr: '' },
        { tag: 'cv12', group: 'variants', max: 1, labelAr: 'بديل تبرير cv12', noteAr: '' },
        { tag: 'cv13', group: 'variants', max: 1, labelAr: 'بديل تبرير cv13', noteAr: '' },
        { tag: 'cv14', group: 'variants', max: 1, labelAr: 'بديل تبرير cv14', noteAr: '' },
        { tag: 'cv15', group: 'variants', max: 1, labelAr: 'بديل تبرير cv15', noteAr: '' },
        { tag: 'cv16', group: 'variants', max: 1, labelAr: 'بديل تبرير cv16', noteAr: '' },
        { tag: 'cv17', group: 'variants', max: 1, labelAr: 'بديل تبرير cv17', noteAr: '' },
        { tag: 'cv18', group: 'variants', max: 1, labelAr: 'بديل تبرير cv18', noteAr: '' },
        { tag: 'cv19', group: 'variants', max: 1, labelAr: 'بديل تبرير cv19', noteAr: 'المدينة القديمة' },
        {
            tag: 'salt', group: 'variants', max: 1,
            labelAr: 'أشكال أسلوبية (salt)',
            noteAr: 'المدينة القديمة — يُفعَّل غالباً مع cv*',
        },

        { tag: 'liga', group: 'liga', max: 1, labelAr: 'تراكيب اختيارية (liga)', noteAr: '' },
        { tag: 'rlig', group: 'liga', max: 1, labelAr: 'تراكيب لازمة (rlig)', noteAr: '' },
        { tag: 'calt', group: 'liga', max: 1, labelAr: 'بدائل سياقية (calt)', noteAr: '' },
        { tag: 'locl', group: 'liga', max: 1, labelAr: 'أشكال محلية (locl)', noteAr: '' },
        { tag: 'ccmp', group: 'liga', max: 1, labelAr: 'تركيب علامات (ccmp)', noteAr: '' },
        { tag: 'mark', group: 'liga', max: 1, labelAr: 'تموضع الحركات (mark)', noteAr: '' },
        { tag: 'mkmk', group: 'liga', max: 1, labelAr: 'تموضع فوق الحركات (mkmk)', noteAr: '' },

        {
            tag: 'ss01',
            group: 'quran',
            max: 1,
            labelAr: 'مجموعة أسلوبية ss01',
            noteAr: 'Digital Khatt — تبديلات شكلية إضافية (ليست ميم خنجرية وحدها)',
        },
    ];

    const DK_TAGS = [
        'jalt', 'cv01', 'cv02', 'cv03',
        'cv10', 'cv11', 'cv12', 'cv13', 'cv14', 'cv15', 'cv16', 'cv17', 'cv18',
        'ss01', 'liga', 'rlig', 'calt', 'ccmp', 'mark', 'mkmk',
    ];
    const OLD_MADINA_TAGS = [
        'salt', 'cv01', 'cv02', 'cv03', 'cv04',
        'cv10', 'cv11', 'cv12', 'cv13', 'cv14', 'cv15', 'cv16', 'cv17', 'cv18', 'cv19',
        'liga', 'rlig', 'calt', 'ccmp', 'mark', 'mkmk',
    ];
    const SHAMIYA_TAGS = [
        'jalt',
        'jt01', 'jt02', 'jt03', 'jt04', 'jt05',
        'kt01', 'kt02', 'kt03', 'kt04', 'kt05',
        'dc01', 'dc02', 'dc03',
        'cv01', 'cv02', 'cv03',
        'cv10', 'cv11', 'cv12', 'cv13', 'cv14', 'cv15', 'cv16', 'cv17', 'cv18',
        'liga', 'rlig', 'calt', 'ccmp', 'mark', 'mkmk',
    ];
    const KATYPICAL_TAGS = ['jalt', 'liga', 'rlig', 'calt', 'ccmp', 'mark', 'mkmk'];
    const UTHMANI_TAGS = ['liga', 'rlig', 'calt', 'locl', 'ccmp', 'mark', 'mkmk', 'ss01'];
    const AMIRI_TAGS = ['liga', 'rlig', 'calt', 'locl', 'ccmp', 'mark', 'mkmk'];
    const INDOPAK_TAGS = ['liga', 'rlig', 'calt', 'locl', 'ccmp', 'mark', 'mkmk'];

    const FONTS = [
        {
            id: 'digital_khatt',
            family: 'Digital Khatt',
            labelAr: 'Digital Khatt (المدينة ١٤٢١)',
            fileHint: 'digitalkhatt.woff2',
            noteAr: 'cv01 يمسّ كاف (uni0643) مباشرة — أفضل خط لتجربة «كاف بديلة/ممتدة» هنا.',
            colrPalette: true,
            supportedTags: DK_TAGS,
            featureMax: { cv01: 12, cv02: 12, cv03: 1 },
        },
        {
            id: 'old_madina',
            family: 'Old Madina',
            labelAr: 'المدينة القديمة (Old Madina)',
            fileHint: 'oldmadina.woff2',
            noteAr: 'أسماء واضحة: kaf.init.ii/iii، meem.isol.ii، kaf.fina.expa — cv01/cv02 سلالم تمديد.',
            supportedTags: OLD_MADINA_TAGS,
            featureMax: { cv01: 12, cv02: 12, cv03: 1, cv04: 5 },
        },
        {
            id: 'al_shamiya',
            family: 'Al Shamiya',
            labelAr: 'الشامية (الكويت)',
            fileHint: 'alshamiya.woff2',
            noteAr: 'أقوى كشيدة منحنية (jt/kt). cv* موجودة أيضاً للبدائل.',
            supportedTags: SHAMIYA_TAGS,
            featureMax: { cv01: 12, cv02: 12, cv03: 1 },
        },
        {
            id: 'katypical',
            family: 'KATypical Naskh',
            labelAr: 'KATypical (مصحف قطر)',
            fileHint: 'KATypicalNaskhv2.0-Regular.woff2',
            noteAr: 'تبرير ثنائي: بدون / مع jalt فقط — بلا سلم كاف/ميم cv.',
            supportedTags: KATYPICAL_TAGS,
        },
        {
            id: 'uthmanic_hafs',
            family: 'UthmanicHafs',
            labelAr: 'عثماني حفص (QPC)',
            fileHint: 'uthmanic_hafs_v20.woff2',
            noteAr: 'رسم عثماني — الميم الخنجرية تأتي من النص لا من cv.',
            supportedTags: UTHMANI_TAGS,
        },
        {
            id: 'amiri_quran',
            family: 'AmiriQuran',
            labelAr: 'Amiri Quran',
            fileHint: 'amiri_quran.woff2',
            noteAr: 'خط الأزهر — بلا سلم كشيدة jt/kt أو cv كاف/ميم.',
            supportedTags: AMIRI_TAGS,
        },
        {
            id: 'indopak',
            family: 'IndoPakNastaleeq2',
            labelAr: 'إندوباك نستعليق',
            fileHint: 'indopak.woff2',
            noteAr: 'رسم هندي — اختبر liga/calt والتموضع.',
            supportedTags: INDOPAK_TAGS,
        },
        {
            id: 'uthmanic_warsh',
            family: 'UthmanicWarsh',
            labelAr: 'عثماني ورش',
            fileHint: 'uthmanic_warsh_v21.woff2',
            noteAr: 'رواية ورش — نفس عائلة العثماني مع اختلافات الرسم.',
            supportedTags: UTHMANI_TAGS,
        },
    ];

    /**
     * Feature-probing snippets. tagsHint lists toggles likely to change
     * appearance; Unicode specials (ميم خنجرية U+06E2) must be in the text.
     */
    const SAMPLES = [
        {
            id: 'hakeem',
            labelAr: 'حكيم — كاف + ميم (جرّب cv01 ثم cv02)',
            tagsHint: ['cv01', 'cv02', 'jalt'],
            text: 'وَهُوَ ٱلْعَزِيزُ ٱلْحَكِيمُ',
            noteAr: 'نفس الكلمة بأشكال متعددة: cv01 يغيّر رسم الكاف/الوصل، cv02 يمدّ الميم، jalt يطيل الاتصال.',
        },
        {
            id: 'alaykum',
            labelAr: 'عليكم — ميم ختامية + اتصال',
            tagsHint: ['cv01', 'cv02', 'jalt', 'mark'],
            text: 'ٱلسَّلَامُ عَلَيْكُمْ',
            noteAr: 'راقب ذيل الميم في «كم» عند رفع cv02، والكشيدة قبلها مع jalt.',
        },
        {
            id: 'rahman',
            labelAr: 'الرحمن — اتصال طويل للكشيدة',
            tagsHint: ['jalt', 'jt01', 'kt01', 'cv01', 'cv02'],
            text: 'ٱلرَّحْمَٰنِ عَلَى ٱلْعَرْشِ ٱسْتَوَىٰ',
        },
        {
            id: 'basmala',
            labelAr: 'البسملة — تراكيب الله / لام-ألف',
            tagsHint: ['liga', 'rlig', 'calt'],
            text: 'بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ',
        },
        {
            id: 'yastahyii',
            labelAr: 'يستحيي — ياءات متصلة',
            tagsHint: ['jalt', 'jt01', 'kt01', 'cv02', 'cv03'],
            text: 'إِنَّ ٱللَّهَ لَا يَسْتَحْىِۦٓ أَن يَضْرِبَ مَثَلًا',
        },
        {
            id: 'samawat',
            labelAr: 'السموات — مدود واتصالات',
            tagsHint: ['jalt', 'jt02', 'kt02', 'salt', 'cv01'],
            text: 'ٱللَّهُ ٱلَّذِى خَلَقَ ٱلسَّمَٰوَٰتِ وَٱلْأَرْضَ',
        },
        {
            id: 'kaf_forms',
            labelAr: 'كاف في مواضع مختلفة',
            tagsHint: ['cv01', 'cv03', 'jalt'],
            text: 'كِتَٰبٌ · يَكْتُبُونَ · مَلِكِ · ٱلْكِتَٰبُ',
            noteAr: 'قارن كافًا ابتدائية/وسطية/قبل لام. في المدينة القديمة cv03 قد يبدّل عائلة الكاف (ii).',
        },
        {
            id: 'meem_forms',
            labelAr: 'ميم بديلة — مواضع متعددة',
            tagsHint: ['cv02', 'cv01', 'jalt'],
            text: 'مِنْ · ٱلْحَمْدُ · رَحِيمٍ · حَكِيمٍ',
            noteAr: 'ميم منعزلة/ابتدائية/ختامية. ارفع cv02 تدريجياً ولاحظ تغيّر الانحناء.',
        },
        {
            id: 'meem_khanjariyya',
            labelAr: 'ميم خنجرية (U+06E2) — علامة في النص',
            tagsHint: ['mark', 'mkmk', 'ccmp', 'ss01'],
            text: 'عَلَيْهِمْۗ\u06E2 وَلَا ٱلضَّآلِّينَ',
            noteAr: 'هذه ليست cv: الرمز موجود في النص. التبديلات تُحرّك موضع العلامة فقط.',
        },
        {
            id: 'allah_ligature',
            labelAr: 'لفظ الجلالة — ligature',
            tagsHint: ['liga', 'rlig', 'calt'],
            text: 'ٱللَّهُ لَا إِلَٰهَ إِلَّا هُوَ ٱلْحَىُّ ٱلْقَيُّومُ',
        },
        {
            id: 'ayah_end',
            labelAr: 'نهاية آية + أرقام (COLR في Digital Khatt)',
            tagsHint: ['liga', 'calt'],
            text: 'ٱلْحَمْدُ لِلَّهِ رَبِّ ٱلْعَٰلَمِينَ ۝١ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ ۝٢',
            noteAr: 'في Digital Khatt تظهر علامات الآية ملوّنة (COLR) — جرّب الوضع الليلي.',
        },
        {
            id: 'heavy_marks',
            labelAr: 'حركات متراكبة — mark / mkmk',
            tagsHint: ['mark', 'mkmk', 'ccmp'],
            text: 'أُو۟لَٰٓئِكَ عَلَىٰ هُدًى مِّن رَّبِّهِمْ وَأُو۟لَٰٓئِكَ هُمُ ٱلْمُفْلِحُونَ',
        },
    ];

    global.AtharFontLabCatalog = {
        GROUPS,
        FEATURES,
        FONTS,
        SAMPLES,
    };
})(window);
