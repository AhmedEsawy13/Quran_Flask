// Return the correct src for an audio_url: local /api/* paths are used directly;
// external https:// URLs are routed through the server-side audio-proxy.
function resolveAudioSrc(audioUrl) {
    if (!audioUrl) return '';
    if (audioUrl.startsWith('/')) return audioUrl;          // already a local path
    return `/api/audio-proxy?url=${encodeURIComponent(audioUrl)}`;
}

document.addEventListener('DOMContentLoaded', async () => {
    const elements = getElements();
    const reciterAudioDataMap = {};
    let quranTextData;
    let currentSegments = [];
    let currentAyahData = null; // Cache for current ayah data
    let currentRepeatCount = 0; // Track current repeat count
    let maxRepeats = 1; // Track maximum repeats set by user
    let isRangeMode = false; // True while a verse range is playing
    let waqfPanelView = 'mushaf'; // 'mushaf' = per-mushaf cards, 'word' = per-word view
    const fontCache = {};
    const loadedShamarlyFonts = new Set();
    let khattRenderVersion = 0;
    let pendingKhattJustifyValue = null;
    let khattJustifyFrameId = 0;

    // ── Per-mushaf color classes ─────────────────────────────────────────────
    // MUST be declared before the first `await` so the const is initialized
    // when loadMushafVersions() → getMushafColorClass() runs.
    const MUSHAF_COLOR_MAP = [
        { match: /المدينة|مدينة/,  cls: 'waqf-mushaf-madinah'  },
        { match: /الشمرلي|شمرلي/,  cls: 'waqf-mushaf-shamarly' },
        { match: /الأزهر|أزهر/,    cls: 'waqf-mushaf-azhar'    },
        { match: /ورش/,            cls: 'waqf-mushaf-warsh'    },
        { match: /الحصري|حصري/,    cls: 'waqf-mushaf-husary'   },
        { match: /الهندي|هندي/,    cls: 'waqf-mushaf-hindi'    },
    ];

    // Arabic display names for reciters (used in the guide title)
    const RECITER_ARABIC_NAMES = {
        'AbdulBaset AbdulSamad (Mujawwad)':    'عبد الباسط عبد الصمد (مجود)',
        'AbdulBaset AbdulSamad (Murattal)':    'عبد الباسط عبد الصمد (مرتل)',
        'Mohamed al-Minshawi (Mujawwad)':      'محمد صديق المنشاوي (مجود)',
        'Mohamed al-Minshawi (Murattal)':      'محمد صديق المنشاوي (مرتل)',
        'Mahmoud Khalil al-Husary (Mujawwad)': 'محمود خليل الحصري (مجود)',
        'Mahmoud Khalil al-Husary (Muallim)':  'محمود خليل الحصري (المعلم)',
        'Ibrahim Al-Akhdar':                   'إبراهيم الأخضر',
        'Ayman Rushdi Suwaid':                 'أيمن رشدي سويد',
        'Mahmoud Ali Al-Banna':                'محمود علي البنا',
        'Mustafa Ismaeel':                     'مصطفى إسماعيل',
    };

    // Set of reciter keys that have positions.db data for the recitation guide
    const RECITERS_WITH_GUIDE = new Set([
        'Mahmoud Khalil al-Husary (Mujawwad)',
        'Mahmoud Khalil al-Husary (Muallim)',
        'Ibrahim Al-Akhdar',
        'Ayman Rushdi Suwaid',
        'Mahmoud Ali Al-Banna',
        'Mustafa Ismaeel',
        'AbdulBaset AbdulSamad (Mujawwad)',
        'AbdulBaset AbdulSamad (Murattal)',
        'Mohamed al-Minshawi (Murattal)',
    ]);

    // Load user preferences and wire UI only after the guide-related consts are initialized.
    loadUserPreferences();
    addEventListeners();

    function getMushafColorClass(version) {
        if (!version) return 'waqf-mushaf-other';
        for (const entry of MUSHAF_COLOR_MAP) {
            if (entry.match.test(version)) return entry.cls;
        }
        return 'waqf-mushaf-other';
    }

    try {
        await loadInitialData();
        // Initialize repeat functionality
        handleRepeatChange();
    } catch (error) {
        handleError('Error loading data:', error, elements.quranTextContainer, 'خطأ في تحميل البيانات. يرجى المحاولة مرة أخرى لاحقًا.');
    }
    
    // User preferences management
    function loadUserPreferences() {
        // Load theme preference
        const savedTheme = localStorage.getItem('quranApp_theme');
        if (savedTheme === 'dark') {
            document.body.classList.add('dark-mode');
            elements.darkModeToggle.checked = true;
        } else if (savedTheme === 'sepia') {
            document.body.classList.add('sepia-mode');
            elements.sepiaModeToggle.checked = true;
        }
        
        // Load font preference
        const savedFont = localStorage.getItem('quranApp_font');
        if (savedFont && elements.quranTextSelect) {
            elements.quranTextSelect.value = savedFont;
            changeFont(savedFont);
        }
        
        // Load khatt justification slider preference
        const savedKhattJustify = parseInt(localStorage.getItem('quranApp_khattJustify') ?? '50', 10);
        if (elements.khattJustifySlider) elements.khattJustifySlider.value = savedKhattJustify;
        if (elements.khattJustifyValue) elements.khattJustifyValue.textContent = savedKhattJustify + '%';

        document.body.dataset.tajweedEnabled = localStorage.getItem('quranApp_tajweedEnabled') === 'true' ? 'true' : 'false';
        updateTajweedButton();
        
        // Load reciter preference
        const savedReciter = localStorage.getItem('quranApp_reciter');
        if (savedReciter && elements.reciterSelect) {
            elements.reciterSelect.value = savedReciter;
        }
        updateGuideButtonAvailability();

        // Load waqf mode preference
        const savedWaqfMode = localStorage.getItem('quranApp_waqfMode') || 'both';
        setWaqfMode(savedWaqfMode);

        // Load last position (surah:ayah)
        const savedPosition = localStorage.getItem('quranApp_lastPosition');
        if (savedPosition) {
            const [surah, ayah] = savedPosition.split(':');
            // Will be applied after surahs load
            elements.surahSelect.dataset.savedSurah = surah;
            elements.ayahSelect.dataset.savedAyah = ayah;
        }
    }
    
    function saveUserPreferences() {
        // Save current position
        const surah = elements.surahSelect.value;
        const ayah = elements.ayahSelect.value;
        if (surah && ayah) {
            localStorage.setItem('quranApp_lastPosition', `${surah}:${ayah}`);
        }
        
        // Save reciter preference
        if (elements.reciterSelect.value) {
            localStorage.setItem('quranApp_reciter', elements.reciterSelect.value);
        }
        
        // Save font preference
        if (elements.quranTextSelect.value) {
            localStorage.setItem('quranApp_font', elements.quranTextSelect.value);
        }

        localStorage.setItem('quranApp_mushafVersions', JSON.stringify(getSelectedMushafVersions()));

        localStorage.setItem('quranApp_waqfMode', getCurrentWaqfMode());
    }

    // Initialize Tippy.js on the button with fallback
    try {
        if (typeof tippy !== 'undefined') {
            tippy('#start-voice-command', {
                content: ' لطريقة أسرع للتنقل بين السور والآيات استخدم الأوامر الصوتية بهذا الشكل: "Go to chapter X verse Y" ',
                placement: 'top',
            });
        }
    } catch (error) {
        console.warn('Tippy.js not loaded, tooltips disabled:', error);
    }

    // Voice recognition
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
        try {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            const recognition = new SpeechRecognition();
            recognition.lang = 'en-US';
            recognition.continuous = false;
            recognition.interimResults = false;

            recognition.onresult = function(event) {
                try {
                    const transcript = event.results[0][0].transcript.toLowerCase();
                    handleVoiceCommand(transcript);
                } catch (error) {
                    console.error('Error processing speech result:', error);
                }
            };

            recognition.onerror = function(event) {
                console.error('Speech recognition error:', event.error);
            };

            const voiceButton = document.getElementById('start-voice-command');
            if (voiceButton) {
                voiceButton.addEventListener('click', () => {
                    try {
                        recognition.start();
                    } catch (error) {
                        console.error('Error starting speech recognition:', error);
                    }
                });
            }
        } catch (error) {
            console.error('Error initializing speech recognition:', error);
        }
    } else {
        const voiceButton = document.getElementById('start-voice-command');
        if (voiceButton) {
            voiceButton.disabled = true;
            voiceButton.title = 'Speech recognition not supported in this browser';
        }
    }

    async function handleVoiceCommand(command) {
        try {
            const surahMatch = command.match(/chapter (\d+)/);
            const ayahMatch = command.match(/verse (\d+)/);

            if (surahMatch) {
                const surahNumber = parseInt(surahMatch[1], 10);
                if (surahNumber >= 1 && surahNumber <= 114) {
                    elements.surahSelect.value = surahNumber;
                    await loadAyahs();
                    if (ayahMatch) {
                        const ayahNumber = parseInt(ayahMatch[1], 10);
                        if (ayahNumber >= 1) {
                            elements.ayahSelect.value = ayahNumber;
                            await loadQuranData(surahNumber, ayahNumber);
                        }
                    }
                }
            } else if (ayahMatch) {
                const ayahNumber = parseInt(ayahMatch[1], 10);
                if (ayahNumber >= 1) {
                    elements.ayahSelect.value = ayahNumber;
                    await loadQuranData(elements.surahSelect.value, ayahNumber);
                }
            }
        } catch (error) {
            console.error('Error handling voice command:', error);
        }
    }
    
    async function loadInitialData() {
        await loadMushafVersions();
        await loadSurahData();
        await loadQuranTextData();
        updateGlobalAyahToVerseKey();
    }

    function getSelectedMushafVersions() {
        const container = document.getElementById('mushaf-version-dropdown');
        if (!container) return [];
        return Array.from(container.querySelectorAll('button.mushaf-pill.active')).map(btn => btn.value);
    }

    // Each Quran font may carry waqf marks from a specific mushaf tradition.
    // When the user picks such a font, auto-activate the matching pill so the
    // marks render without requiring an extra click. Kept inside the function
    // so it can't be read while still in the temporal dead zone — loadInitialData
    // is awaited before this scope's top-level const declarations run.
    function ensureDefaultMushafsForFont(font) {
        const FONT_DEFAULT_MUSHAFS = {
            amiri_quran: ['الأزهر'],
        };
        const defaults = FONT_DEFAULT_MUSHAFS[font];
        if (!defaults || !defaults.length) return false;
        const container = document.getElementById('mushaf-version-dropdown');
        if (!container) return false;
        let changed = false;
        defaults.forEach((version) => {
            const btn = Array.from(container.querySelectorAll('button.mushaf-pill'))
                .find((b) => b.value === version);
            if (btn && !btn.classList.contains('active')) {
                btn.classList.add('active');
                changed = true;
            }
        });
        if (changed) {
            localStorage.setItem('quranApp_mushafVersions',
                JSON.stringify(getSelectedMushafVersions()));
        }
        return changed;
    }

    function updateMushafVersionSummary() {
        // No-op: pills are always visible; summary span is no longer shown.
    }

    async function loadMushafVersions() {
        const dropdown = document.getElementById('mushaf-version-dropdown');
        if (!dropdown) return;

        dropdown.innerHTML = '';
        try {
            const versions = await fetchData('/api/mushaf-versions');
            if (Array.isArray(versions)) {
                const filtered = versions.filter((v) => !['token_index', 'word_index'].includes(v));
                const saved = JSON.parse(localStorage.getItem('quranApp_mushafVersions') || '[]');
                filtered.forEach((version) => {
                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.value = version;
                    btn.textContent = version;
                    const colorCls = getMushafColorClass(version);
                    btn.className = 'mushaf-pill ' + colorCls;
                    if (saved.includes(version)) btn.classList.add('active');
                    btn.addEventListener('click', () => {
                        const wasPlaying = !elements.audioElement.paused;
                        const savedTime = elements.audioElement.currentTime;
                        btn.classList.toggle('active');
                        localStorage.setItem('quranApp_mushafVersions',
                            JSON.stringify(getSelectedMushafVersions()));
                        loadQuranData().then(() => {
                            elements.audioElement.currentTime = savedTime;
                            if (wasPlaying) {
                                elements.audioElement.play().catch(() => {});
                                updatePlayPauseButton();
                            }
                        });
                    });
                    dropdown.appendChild(btn);
                });
                ensureDefaultMushafsForFont(elements.quranTextSelect?.value);
            }
        } catch (error) {
            console.error('Error loading Mushaf versions:', error);
        }
    }

    function getElements() {
        return {
            quranTextContainer: document.getElementById('quran-text'),
            transliterationContainer: document.getElementById('transliteration'),
            tafseerContainer: document.getElementById('tafseer-text'),
            eerabContainer: document.getElementById('eerab-text'),
            wordMeaningContainer: document.getElementById('word-meaning-text'),
            audioElement: document.getElementById('quran-audio'),
            repeatSelect: document.getElementById('repeat-select'),
            reciterSelect: document.getElementById('reciter-select'),
            surahSelect: document.getElementById('surah-select'),
            ayahSelect: document.getElementById('ayah-select'),
            startAyahSelect: document.getElementById('start-ayah-select'),
            endAyahSelect: document.getElementById('end-ayah-select'),
            nextAyahButton: document.getElementById('next-ayah'),
            prevAyahButton: document.getElementById('prev-ayah'),
            playRangeButton: document.getElementById('play-range'),
            darkModeToggle: document.getElementById('dark-mode-toggle'),
            sepiaModeToggle: document.getElementById('sepia-mode-toggle'),
            showRangeSelection: document.getElementById('show-range-selection'),
            rangeSelection: document.getElementById('range-selection'),
            modal: document.getElementById('rangeModal'),
            modalContent: document.querySelector('#rangeModal .modal-content'),
            closeModal: document.querySelector('#rangeModal .close'),
            quranTextSelect: document.getElementById('quran-text-select'),
            readingViewSelect: document.getElementById('reading-view-select'),
            mushafVersionMultiselect: document.getElementById('mushaf-version-multiselect'),
            waqfModeControl: document.getElementById('waqf-mode-control'),
            playPauseButton: document.getElementById('play-pause-button'),
            toggleWordMeaningButton: document.getElementById('toggle-word-meaning-button'),
            bookmarkButton: document.getElementById('bookmark-button'),
            showBookmarksButton: document.getElementById('show-bookmarks-button'),
            bookmarksModal: document.getElementById('bookmarksModal'),
            bookmarksList: document.getElementById('bookmarks-list'),
            closeBookmarksModal: document.querySelector('.close-bookmarks'),
            khattJustifyRow: document.getElementById('khatt-justify-row'),
            khattJustifySlider: document.getElementById('khatt-justify-slider'),
            khattJustifyValue: document.getElementById('khatt-justify-value'),
        };
    }

    function addEventListeners() {
        elements.darkModeToggle.addEventListener('change', toggleDarkMode);
        elements.sepiaModeToggle.addEventListener('change', toggleSepiaMode);
        // Range button opens the modal directly (showModal registered below)
        elements.reciterSelect.addEventListener('change', onReciterChange);
        elements.surahSelect.addEventListener('change', loadAyahs);
        if (elements.readingViewSelect) {
            elements.readingViewSelect.addEventListener('change', loadQuranData);
        }
        // mushaf-version change listeners are set up in loadMushafVersions()
        if (elements.waqfModeControl) {
            elements.waqfModeControl.addEventListener('click', (e) => {
                const btn = e.target.closest('.waqf-mode-btn');
                if (btn) setWaqfMode(btn.dataset.mode);
            });
        }
        elements.ayahSelect.addEventListener('change', () => {
            // Clean up range mode if active when user manually changes ayah
            if (elements.playPauseButton.rangePlayPauseHandler) {
                cleanupRangeMode();
            }
            loadQuranData();
        });
        
        // Bookmark event listeners
        if (elements.bookmarkButton) {
            elements.bookmarkButton.addEventListener('click', addBookmark);
        }
        if (elements.showBookmarksButton) {
            elements.showBookmarksButton.addEventListener('click', showBookmarksModal);
        }
        if (elements.closeBookmarksModal) {
            elements.closeBookmarksModal.addEventListener('click', hideBookmarksModal);
        }
        window.addEventListener('click', (event) => {
            if (event.target === elements.bookmarksModal) {
                hideBookmarksModal();
            }
        });
        elements.nextAyahButton.addEventListener('click', loadNextAyah);
        elements.prevAyahButton.addEventListener('click', loadPrevAyah);
        elements.playRangeButton.addEventListener('click', playRange);
        elements.showRangeSelection.addEventListener('click', showModal);
        elements.closeModal.addEventListener('click', closeModal);
        elements.startAyahSelect.addEventListener('change', () => {
            const startIdx = elements.startAyahSelect.selectedIndex;
            if (elements.endAyahSelect.selectedIndex <= startIdx) {
                const nextIdx = Math.min(startIdx + 1, elements.endAyahSelect.options.length - 1);
                elements.endAyahSelect.selectedIndex = nextIdx;
            }
        });
        window.addEventListener('click', (event) => {
            if (event.target === elements.modal) closeModal();
        });
        elements.quranTextSelect.addEventListener('change', async () => {
            // Add loading indicator
            const originalText = elements.quranTextContainer.innerHTML;
            elements.quranTextContainer.innerHTML = '<div class="loading">جاري تحميل الخط الجديد...</div>';
            
            try {
                changeFont(elements.quranTextSelect.value);
                ensureDefaultMushafsForFont(elements.quranTextSelect.value);
                await loadQuranTextData();
                currentAyahData = null; // force re-fetch with correct source param for the new font
                await updateDisplayedText();
            } catch (error) {
                console.error('Error changing font:', error);
                elements.quranTextContainer.innerHTML = originalText;
                handleError('Error changing font:', error, elements.quranTextContainer, 'خطأ في تغيير الخط. يرجى المحاولة مرة أخرى.');
            }
        });
        elements.playPauseButton.addEventListener('click', togglePlayPause);

        // Digital Khatt justification slider
        if (elements.khattJustifySlider) {
            elements.khattJustifySlider.addEventListener('input', () => {
                const val = parseInt(elements.khattJustifySlider.value, 10);
                applyKhattJustify(val);
                if (elements.khattJustifyValue) elements.khattJustifyValue.textContent = val + '%';
                localStorage.setItem('quranApp_khattJustify', val);
            });
        }
        const khattResetBtn = document.getElementById('khatt-justify-reset');
        if (khattResetBtn) {
            khattResetBtn.addEventListener('click', () => {
                const defaultVal = 50;
                applyKhattJustify(defaultVal);
                if (elements.khattJustifySlider) elements.khattJustifySlider.value = defaultVal;
                if (elements.khattJustifyValue) elements.khattJustifyValue.textContent = defaultVal + '%';
                localStorage.setItem('quranApp_khattJustify', defaultVal);
            });
        }

        document.getElementById('show-transliteration').addEventListener('click', toggleTransliteration);
        document.getElementById('show-tafseer').addEventListener('click', toggleTafseer);
        const eerabBtn = document.getElementById('show-eerab');
        if (eerabBtn) eerabBtn.addEventListener('click', toggleEerab);
        const tajweedBtn = document.getElementById('show-tajweed');
        if (tajweedBtn) tajweedBtn.addEventListener('click', toggleTajweed);
        const nuzoolBtn = document.getElementById('show-nuzool');
        if (nuzoolBtn) nuzoolBtn.addEventListener('click', toggleNuzool);
        elements.toggleWordMeaningButton.addEventListener('click', toggleWordMeaning); // Listener for the new toggle via button

        const guideBtn = document.getElementById('show-recitation-guide');
        if (guideBtn) guideBtn.addEventListener('click', toggleRecitationGuide);

        const legendToggle = document.getElementById('waqf-legend-toggle');
        if (legendToggle) legendToggle.addEventListener('click', () => {
            const legend = document.getElementById('waqf-legend');
            if (legend) {
                const hidden = legend.hasAttribute('hidden');
                if (hidden) { legend.removeAttribute('hidden'); } else { legend.setAttribute('hidden', ''); }
            }
        });

        const tajweedLegendToggle = document.getElementById('tajweed-legend-toggle');
        if (tajweedLegendToggle) tajweedLegendToggle.addEventListener('click', () => {
            const legend = document.getElementById('tajweed-legend');
            if (!legend) return;
            const hidden = legend.hasAttribute('hidden');
            if (hidden) { legend.removeAttribute('hidden'); } else { legend.setAttribute('hidden', ''); }
            tajweedLegendToggle.classList.toggle('active', hidden);
        });

        const waqfTableBtn = document.getElementById('toggle-waqf-table');
        if (waqfTableBtn) {
            waqfTableBtn.addEventListener('click', () => {
                const tableContainer = document.getElementById('waqf-verse-table-container');
                if (!tableContainer) return;
                const isHidden = tableContainer.hidden;
                if (isHidden) {
                    tableContainer.removeAttribute('hidden');
                    waqfTableBtn.classList.add('active');
                    renderWaqfVerseTable();
                } else {
                    tableContainer.setAttribute('hidden', '');
                    waqfTableBtn.classList.remove('active');
                }
            });
        }

        // Tab delegation — switching between mushaf / word view inside the open panel
        const waqfContainer = document.getElementById('waqf-verse-table-container');
        if (waqfContainer) {
            waqfContainer.addEventListener('click', e => {
                const tab = e.target.closest('[data-waqf-view]');
                if (!tab) return;
                waqfPanelView = tab.dataset.waqfView;
                renderWaqfVerseTable();
            });
        }

        // Add keyboard event listeners for arrow key navigation
        document.addEventListener('keydown', handleKeydown);
    }
    
    function handleKeydown(event) {
        // Only handle arrow keys when not typing in input fields
        if (event.target.tagName === 'INPUT' || event.target.tagName === 'SELECT' || event.target.tagName === 'TEXTAREA') {
            return;
        }
        
        switch (event.key) {
            case 'ArrowLeft':
                event.preventDefault();
                loadPrevAyah();
                break;
            case 'ArrowRight':
                event.preventDefault();
                loadNextAyah();
                break;
        }
    }

    async function onReciterChange() {
        updateGuideButtonAvailability();
        await loadQuranData();
        updatePlayPauseButton();
    }

    function updateGuideButtonAvailability() {
        const guideBtn = document.getElementById('show-recitation-guide');
        if (!guideBtn) return;
        const reciter = elements.reciterSelect.value;
        const hasGuide = RECITERS_WITH_GUIDE.has(reciter);
        if (hasGuide) {
            guideBtn.removeAttribute('data-guide-unavailable');
            guideBtn.title = 'دليل التلاوة وفق علامات الوقف';
        } else {
            guideBtn.setAttribute('data-guide-unavailable', '');
            guideBtn.title = `دليل التلاوة غير متاح لـ ${RECITER_ARABIC_NAMES[reciter] || reciter}`;
        }
    }

    async function loadSurahData() {
        try {
            // Use local API endpoint instead of external API for faster loading
            const surahData = await fetchData('/api/surahs');
            const formattedSurahData = surahData.map(surah => ({
                number: surah.number,
                name: `${surah.number}. ${surah.name}`
            }));
            populateSelectOptions(formattedSurahData, elements.surahSelect, 'number', 'name');
            
            // Restore last saved surah position
            const savedSurah = elements.surahSelect.dataset.savedSurah;
            if (savedSurah) {
                const surahOption = Array.from(elements.surahSelect.options).find(opt => opt.value === savedSurah);
                if (surahOption) {
                    elements.surahSelect.value = savedSurah;
                }
            }
        } catch (error) {
            console.error('Error loading surah data:', error);
            // Fallback: Create a basic list of surahs (1-114)
            const fallbackSurahs = Array.from({length: 114}, (_, i) => ({
                number: i + 1,
                name: `${i + 1}. سورة ${i + 1}`
            }));
            populateSelectOptions(fallbackSurahs, elements.surahSelect, 'number', 'name');
        }
    }

    async function loadQuranTextData() {
        const font = elements.quranTextSelect.value;
        const source = font === 'shamarly' ? 'qpc_hafs' : font;
        if (!fontCache[font]) {
            quranTextData = await fetchData(`/api/quran-text?source=${source}`);
            fontCache[font] = quranTextData;
        } else {
            quranTextData = fontCache[font];
        }
        window.quranTextData = quranTextData; // expose for memo overlay
        updateGlobalAyahToVerseKey();
    }

    // Waqf ruling chars to strip from IndoPak inline text in 'selected'/'none' modes.
    // Keeps verse-end circle ۟ (U+06DF), structural marks (U+06E0–U+06E6), and PUA
    // verse-number glyphs (U+E000+) so the verse circle still renders correctly.
    const INDOPAK_INLINE_WAQF_STRIP = /[\u0614\u0615\u0617\u06D6-\u06DC\u06EA\u06EB\u06ED]/g;

    function getDisplayedAyahText(verseEntry = {}, fallbackText = '') {
        const font = elements.quranTextSelect.value;
        const waqfMode = getCurrentWaqfMode();
        const isIndoPak = font === 'indopak_nastaleeq' || font === 'indopak_nastaleeq_2';

        if (isIndoPak) {
            if (waqfMode === 'original' || waqfMode === 'both') {
                // Show text with embedded waqf marks
                return verseEntry.text || verseEntry.raw_text || fallbackText || '';
            }
            // 'selected' or 'none' — strip only waqf ruling marks, keep verse-end circle + PUA
            const base = verseEntry.text || verseEntry.raw_text || fallbackText || '';
            return base.replace(INDOPAK_INLINE_WAQF_STRIP, '');
        }

        return verseEntry.text || fallbackText;
    }

    function updateGlobalAyahToVerseKey() {
        const globalAyahToVerseKey = {};
        for (const verseKey in quranTextData) {
            const ayahData = quranTextData[verseKey];
            if (ayahData && ayahData.id) globalAyahToVerseKey[ayahData.id] = verseKey;
        }
        window.globalAyahToVerseKey = globalAyahToVerseKey;
    }

    async function loadAyahs() {
        const surahNumber = elements.surahSelect.value;
        try {
            const ayahList = await fetchData(`/api/surahs/${surahNumber}/ayahs`);
            populateSelectOptions(ayahList, elements.ayahSelect, null, null, 'آية');
            populateSelectOptions(ayahList, elements.startAyahSelect, null, null, 'آية');
            populateSelectOptions(ayahList, elements.endAyahSelect, null, null, 'آية');
            
            // Restore last saved ayah position if this is the saved surah
            const savedSurah = elements.surahSelect.dataset.savedSurah;
            const savedAyah = elements.ayahSelect.dataset.savedAyah;
            if (savedSurah === surahNumber && savedAyah) {
                const ayahOption = Array.from(elements.ayahSelect.options).find(opt => opt.value === savedAyah);
                if (ayahOption) {
                    elements.ayahSelect.value = savedAyah;
                }
                // Clear saved data after restoring
                delete elements.surahSelect.dataset.savedSurah;
                delete elements.ayahSelect.dataset.savedAyah;
            }
            
            await loadQuranData();
            updatePlayPauseButton();
        } catch (error) {
            handleError('Error loading Ayahs:', error, elements.quranTextContainer, 'خطأ في تحميل الآيات. يرجى المحاولة مرة أخرى لاحقًا.');
        }
    }

    // Preload next ayah audio for low latency playback
    let preloadedAudio = null;
    function preloadNextAyah() {
        const currentAyahIndex = elements.ayahSelect.selectedIndex;
        if (currentAyahIndex < elements.ayahSelect.options.length - 1) {
            const nextAyahNumber = elements.ayahSelect.options[currentAyahIndex + 1].value;
            const surahNumber = elements.surahSelect.value;
            const reciter = elements.reciterSelect.value;
            
            // Clean up previous preloaded audio to prevent memory leak
            if (preloadedAudio) {
                preloadedAudio.src = '';
                preloadedAudio.load();
                preloadedAudio = null;
            }
            
            // Fetch next ayah data and preload audio
            fetchData(`/api/surahs/${surahNumber}/ayahs/${nextAyahNumber}`)
                .then(data => {
                    if (data.reciters && data.reciters[reciter]) {
                        preloadedAudio = new Audio();
                        preloadedAudio.preload = 'auto';
                        preloadedAudio.src = resolveAudioSrc(data.reciters[reciter].audio_url);
                    }
                })
                .catch(err => console.log('Preload failed (non-critical):', err));
        }
    }

    async function loadQuranData() {
        const surahNumber = elements.surahSelect.value;
        const ayahNumber = elements.ayahSelect.value;
        if (!ayahNumber) return;
    
        try {
            const font = elements.quranTextSelect.value;
            const readingView = elements.readingViewSelect?.value || 'verse-normal';
            const selectedVersions = getSelectedMushafVersions();
            const mushafVersion = selectedVersions[0] || '';

            if (font === 'shamarly') {
                await loadShamarlyQuranData(surahNumber, ayahNumber, readingView, selectedVersions);
                return;
            }

            const params = new URLSearchParams();
            selectedVersions.forEach((v) => params.append('mushaf_version', v));
            // Tell the backend which text source we're using so it can return
            // the correct embedded waqf symbols (e.g. الهندي for IndoPak fonts).
            if (font === 'indopak_nastaleeq' || font === 'indopak_nastaleeq_2') {
                params.append('source', 'indopak_nastaleeq');
            }
            const query = params.toString() ? '?' + params.toString() : '';
            currentAyahData = await fetchData(`/api/surahs/${surahNumber}/ayahs/${ayahNumber}${query}`);
            const verseKey = `${surahNumber}:${ayahNumber}`;
            const globalAyahNumber = currentAyahData.id;
            if (!globalAyahNumber) throw new Error(`No global Ayah number found for Surah ${surahNumber}, Ayah ${ayahNumber}`);
    
            const reciter = elements.reciterSelect.value;
            const reciterAudio = currentAyahData.reciters[reciter];
            if (!reciterAudio) throw new Error('Reciter audio not found');
    
            // Use already cached quranTextData instead of making redundant API call.
            const _verseEntry = quranTextData?.[verseKey] || {};
                const ayahText = getDisplayedAyahText(_verseEntry, currentAyahData.text || currentAyahData.raw_text || '');
    
            elements.audioElement.src = resolveAudioSrc(reciterAudio.audio_url);
            currentSegments = reciterAudio.segments;
            displayQuranicText(ayahText, currentSegments, currentAyahData.waqf_symbols || []);
            renderWaqfVerseTable();
            displayTransliteration(currentAyahData.transliteration);
            await maybeRefreshTafseer(surahNumber, ayahNumber);
            await maybeRefreshEerab(surahNumber, ayahNumber);
            await maybeRefreshTajweed(surahNumber, ayahNumber);
            // Only display word meanings if they should be visible
            if (elements.wordMeaningVisible) {
                displayWordMeanings(currentAyahData.word_meanings_ordered || currentAyahData.word_meanings || {}, ayahText);
            } else {
                elements.wordMeaningContainer.innerHTML = '';
            }
            updatePlayPauseButton();
            
            // Refresh recitation guide if visible
            const guideContainer = document.getElementById('recitation-guide-container');
            if (guideContainer && guideContainer.style.display !== 'none') {
                await fetchAndBuildRecitationGuide();
            }

            // Save current position to localStorage
            saveUserPreferences();
            
            // Preload next ayah for low latency navigation
            preloadNextAyah();
    
            elements.audioElement.onended = updatePlayPauseButton;
        } catch (error) {
            handleError('Error loading Quran data:', error, elements.quranTextContainer, 'خطأ في تحميل البيانات. يرجى المحاولة مرة أخرى لاحقًا.');
        }
    }

    async function loadShamarlyQuranData(surahNumber, ayahNumber, readingView, mushafVersions) {
        currentAyahData = await fetchData(`/api/surahs/${surahNumber}/ayahs/${ayahNumber}`);
        const reciter = elements.reciterSelect.value;
        const reciterAudio = currentAyahData.reciters?.[reciter];
        if (!reciterAudio) throw new Error('Reciter audio not found');

        const versions = Array.isArray(mushafVersions) ? mushafVersions : (mushafVersions ? [mushafVersions] : []);
        // Always include الشمرلي so "original" mode can show Shamarly's own symbols
        const versionsWithOwn = versions.includes('الشمرلي') ? versions : ['الشمرلي', ...versions];        const params = new URLSearchParams();
        versionsWithOwn.forEach((v) => params.append('mushaf_version', v));
        const query = params.toString() ? `?${params.toString()}` : '';

        let shamarlyPayload;
        if (readingView === 'page') {
            shamarlyPayload = await fetchData(`/api/shamarly/page-by-ayah/${surahNumber}/${ayahNumber}${query}`);
        } else {
            shamarlyPayload = await fetchData(`/api/shamarly/ayah/${surahNumber}/${ayahNumber}${query}`);
        }

        if (shamarlyPayload?.font_name) {
            await ensureShamarlyFontLoaded(shamarlyPayload.font_name);
            elements.quranTextContainer.style.fontFamily = `'${shamarlyPayload.font_name}', 'UthmanicHafs', serif`;
        }

        // A verse can span two font-bearing pages; each page's glyphs are page-local,
        // so load every referenced page font (not just the first) before rendering.
        const shamarlyFontPages = Array.isArray(shamarlyPayload?.pages) ? shamarlyPayload.pages : [];
        await Promise.all(
            shamarlyFontPages.map((p) => ensureShamarlyFontLoaded(shamarlyFontName(p)))
        );

        if (readingView === 'page') {
            renderShamarlyPage(shamarlyPayload);
        } else if (readingView === 'verse-mushaf-lines') {
            renderShamarlyVerseLines(shamarlyPayload);
        } else {
            renderShamarlyVerseWords(shamarlyPayload, reciterAudio.segments || []);
        }

        elements.audioElement.src = resolveAudioSrc(reciterAudio.audio_url);
        currentSegments = reciterAudio.segments || [];
        displayTransliteration(currentAyahData.transliteration);
        await maybeRefreshTafseer(surahNumber, ayahNumber);
        await maybeRefreshEerab(surahNumber, ayahNumber);
        await maybeRefreshTajweed(surahNumber, ayahNumber);
        if (elements.wordMeaningVisible) {
            const verseText = shamarlyPayload?.raw_text || currentAyahData.text || '';
            displayWordMeanings(currentAyahData.word_meanings_ordered || currentAyahData.word_meanings || {}, verseText);
        } else {
            elements.wordMeaningContainer.innerHTML = '';
        }

        updatePlayPauseButton();

        // Refresh recitation guide if visible
        const guideContainerSh = document.getElementById('recitation-guide-container');
        if (guideContainerSh && guideContainerSh.style.display !== 'none') {
            await fetchAndBuildRecitationGuide();
        }

        saveUserPreferences();
        preloadNextAyah();
        elements.audioElement.onended = updatePlayPauseButton;
    }

    function shamarlyFontName(pageNumber) {
        return `Shemrly-Page${String(pageNumber).padStart(3, '0')}`;
    }

    async function ensureShamarlyFontLoaded(fontName) {
        if (!fontName || loadedShamarlyFonts.has(fontName)) {
            return;
        }
        try {
            const font = new FontFace(fontName, `url('/static/fonts/${fontName}.ttf') format('truetype')`);
            const loadedFont = await font.load();
            document.fonts.add(loadedFont);
            loadedShamarlyFonts.add(fontName);
        } catch (error) {
            // Fall through: the caller will render with a fallback font instead
            // of erroring out of the whole ayah load. Mark the font as tried so
            // we don't retry on every navigation.
            loadedShamarlyFonts.add(fontName);
            console.warn(`Shamarly font ${fontName} unavailable; using fallback`, error);
        }
    }

    async function updateDisplayedText() {
        const surahNumber = elements.surahSelect.value;
        const ayahNumber = elements.ayahSelect.value;
        if (!ayahNumber) return;

        try {
            if (elements.quranTextSelect.value === 'shamarly') {
                await loadQuranData();
                return;
            }

            // Use cached data if available, otherwise fetch
            if (!currentAyahData || currentAyahData.surah_number !== parseInt(surahNumber) || currentAyahData.ayah_number !== parseInt(ayahNumber)) {
                const _vers = getSelectedMushafVersions();
                const _p = new URLSearchParams();
                _vers.forEach((v) => _p.append('mushaf_version', v));
                const _fontNow = elements.quranTextSelect.value;
                if (_fontNow === 'indopak_nastaleeq' || _fontNow === 'indopak_nastaleeq_2') {
                    _p.append('source', 'indopak_nastaleeq');
                } else if (_fontNow === 'amiri_quran') {
                    _p.append('source', 'amiri_quran');
                }
                const query = _p.toString() ? '?' + _p.toString() : '';
                currentAyahData = await fetchData(`/api/surahs/${surahNumber}/ayahs/${ayahNumber}${query}`);
            }
            
            const verseKey = `${surahNumber}:${ayahNumber}`;
            // Use already cached quranTextData instead of making redundant API call.
            const _verseEntry = quranTextData?.[verseKey] || {};
            const ayahText = getDisplayedAyahText(_verseEntry, currentAyahData.text || currentAyahData.raw_text || '');
            displayQuranicText(ayahText, currentSegments, currentAyahData.waqf_symbols || []);
            renderWaqfVerseTable();
            displayTransliteration(currentAyahData.transliteration);
            await maybeRefreshTafseer(surahNumber, ayahNumber);
            await maybeRefreshEerab(surahNumber, ayahNumber);
            await maybeRefreshTajweed(surahNumber, ayahNumber);
            if (elements.wordMeaningVisible) {
                displayWordMeanings(currentAyahData.word_meanings_ordered || currentAyahData.word_meanings || {}, ayahText);
            } else {
                elements.wordMeaningContainer.innerHTML = '';
            }
        } catch (error) {
            handleError('Error updating Quran text:', error, elements.quranTextContainer, 'خطأ في تحديث النص. يرجى المحاولة مرة أخرى لاحقًا.');
        }
    }

    // Glue standalone waqf-only tokens (e.g. IndoPak's ؕ ۚ ۙ that appear
    // between words) onto the END of the preceding word, so each waqf
    // mark visually attaches to the word it actually belongs to —
    // matching how Hafs/Madina render their combining-mark waqf.
    // The last token (verse-end marker) is preserved as a separate element.
    function mergeWaqfOnlyTokensIntoPrev(rawTokens) {
        const isWaqfOnly = (s) => {
            if (!s) return false;
            const stripped = s.replace(
                /[\u0610-\u061F\u064B-\u065F\u0670\u06D6-\u06ED\u08D0-\u08FF\uF500-\uF6FF\uFE70-\uFEFF]/g,
                ''
            ).trim();
            return stripped === '';
        };
        const out = [];
        for (let i = 0; i < rawTokens.length; i++) {
            const tok = rawTokens[i];
            const isLast = i === rawTokens.length - 1;
            if (isWaqfOnly(tok) && !isLast && out.length > 0) {
                out[out.length - 1] = out[out.length - 1] + tok;
            } else {
                out.push(tok);
            }
        }
        return out;
    }

    function displayQuranicText(text, segments, waqfSymbols = []) {
        elements.quranTextContainer.style.fontFamily = '';
        elements.quranTextContainer.innerHTML = '';
        const words = mergeWaqfOnlyTokensIntoPrev(text.split(' '));
        const wordIndexToSegmentMap = new Map();

        const _waqfMode = getCurrentWaqfMode();
        const _isIndoPak = document.body.dataset.fontType === 'indopak';
        let activeSymbols = waqfSymbols;
        if (_waqfMode === 'none' || _waqfMode === 'original') {
            activeSymbols = [];
        } else if (_waqfMode === 'selected') {
            const selSet = new Set(getSelectedMushafVersions());
            activeSymbols = waqfSymbols.filter(s => selSet.has(s.version || ''));
        } else if (_waqfMode === 'both') {
            const selSet = new Set(getSelectedMushafVersions());
            activeSymbols = waqfSymbols.filter(s => {
                const v = s.version || '';
                if (!selSet.has(v)) return false;
                if (_isIndoPak && v === 'الهندي') return false;
                return true;
            });
        }

        const waqfByToken = buildWaqfByTokenIndex(activeSymbols, words);
        const wordElements = []; // Cache word elements for performance

        // Map segments to words first, before creating word elements
        if (Array.isArray(segments)) {
            mapSegmentsToWords(segments, wordIndexToSegmentMap);
        } else {
            console.error('Invalid segments format:', segments);
        }

        // Now create word elements with populated segment mapping
        for (let i = 0; i < words.length; i++) {
            const word = words[i];
            const wordElement = createWordElement(word, i, wordIndexToSegmentMap);
            const waqfText = waqfByToken.get(i);
            if (waqfText) {
                appendWaqfEntries(wordElement, waqfText);
            }
            wordElements[i] = wordElement; // Cache reference
            elements.quranTextContainer.appendChild(wordElement);
            elements.quranTextContainer.appendChild(document.createTextNode(' '));
        }

        // Remove existing timeupdate listeners to prevent memory leaks
        if (elements.audioElement.timeUpdateHandler) {
            elements.audioElement.removeEventListener('timeupdate', elements.audioElement.timeUpdateHandler);
        }

        // Create throttled highlight function for better performance
        let lastHighlightTime = 0;
        const highlightThrottle = 100; // Throttle to 10 updates per second
        
        // Create and store the new handler
        elements.audioElement.timeUpdateHandler = () => {
            const now = Date.now();
            if (now - lastHighlightTime >= highlightThrottle) {
                highlightWords(wordElements, wordIndexToSegmentMap);
                lastHighlightTime = now;
            }
        };
        
        elements.audioElement.addEventListener('timeupdate', elements.audioElement.timeUpdateHandler);

        refreshKhattRenderedWords();
    }

    function filterWaqfByMode(symbols) {
        const mode = getCurrentWaqfMode();
        const isIndoPak = document.body.dataset.fontType === 'indopak';
        // Shemrly word-glyphs don't carry inline waqf marks, so الشمرلي (the
        // mushaf's own marks) act as the "original" layer — shown as overlays,
        // mirroring how مصحف الأميرية treats its baked-in الأزهر marks.
        const isShamarly = document.body.dataset.fontType === 'shamarly';
        if (!Array.isArray(symbols)) return symbols;
        if (mode === 'none') return [];
        if (mode === 'original') {
            return isShamarly ? symbols.filter(s => (s.version || '') === 'الشمرلي') : [];
        }
        const selSet = new Set(getSelectedMushafVersions());
        if (mode === 'selected') {
            return symbols.filter(s => selSet.has(s.version || ''));
        }
        // 'both' — selected overlays (plus الشمرلي's own marks for Shemrly).
        // For IndoPak, exclude الهندي to avoid duplicating raw_text inline tokens.
        return symbols.filter(s => {
            const v = s.version || '';
            if (isShamarly && v === 'الشمرلي') return true;
            if (!selSet.has(v)) return false;
            if (isIndoPak && v === 'الهندي') return false;
            return true;
        });
    }

    function renderWaqfVerseTable() {
        const container = document.getElementById('waqf-verse-table-container');
        if (!container || container.hidden) return;

        const allSymbols = currentAyahData?.waqf_symbols || [];
        const mode = getCurrentWaqfMode();

        let entries;
        if (mode === 'none') {
            entries = [];
        } else if (mode === 'original') {
            entries = allSymbols;
        } else if (mode === 'selected') {
            const selSet = new Set(getSelectedMushafVersions());
            entries = allSymbols.filter(s => selSet.has(s.version || ''));
        } else {
            entries = allSymbols;
        }

        if (entries.length === 0) {
            const msg = mode === 'none'
                ? 'علامات الوقف مخفية — اختر وضع عرض آخر لرؤية البطاقات'
                : 'لا توجد علامات وقف مسجّلة لهذه الآية';
            container.innerHTML = `<p class="waqf-panel-empty">${msg}</p>`;
            return;
        }

        const surahNum   = elements.surahSelect.value;
        const ayahNum    = elements.ayahSelect.value;
        const verseKey   = `${surahNum}:${ayahNum}`;
        const verseEntry = quranTextData?.[verseKey] || {};

        // Clean verse words for IndoPak word-text lookup (word_index is 1-based)
        const rawVerseText = verseEntry.clean_text || verseEntry.text
            || currentAyahData?.clean_text || currentAyahData?.text || '';
        const cleanVerseText = rawVerseText.replace(/[\u06D5-\u06ED\u0610-\u061A\u08D0-\u08FF]/g, '');
        const verseWords = cleanVerseText.trim().split(/\s+/).filter(Boolean);

        const indopakSymFont = "'IndoPakNastaleeq2', 'Naskh-Nastaleeq-IndoPak-QWBW', serif";

        // Strip waqf combining marks to recover clean word text from a token
        const stripWaqf = s =>
            (s || '').replace(/[\u06D5-\u06ED\u0610-\u061A\u08D0-\u08FF]/g, '').trim();

        function getWordText(entry) {
            const isHindi = /الهندي|هندي/.test(entry.version || '');
            if (!isHindi) {
                const tok = stripWaqf(entry.clean_token || entry.original_token || '');
                if (tok) return tok;
            }
            // الهندي: clean_token is empty → look up by word_index in verse words
            const wIdx = Number(entry.word_index);
            if (wIdx > 0 && wIdx <= verseWords.length) return verseWords[wIdx - 1];
            return '';
        }

        // word_index → Set<version>  (to build "shared with" per word)
        const wordVersionsMap = new Map();
        for (const e of entries) {
            const wIdx = Number(e.word_index) || (Number(e.token_index) + 1);
            if (!wordVersionsMap.has(wIdx)) wordVersionsMap.set(wIdx, new Set());
            wordVersionsMap.get(wIdx).add(e.version || '');
        }

        // Group by mushaf version
        const byMushaf = new Map();
        for (const e of entries) {
            const ver = e.version || 'غير محدد';
            if (!byMushaf.has(ver)) byMushaf.set(ver, []);
            byMushaf.get(ver).push(e);
        }

        const ORDER = ['المدينة', 'الشمرلي', 'الأزهر', 'ورش', 'الحصري', 'الهندي'];
        const sortedMushafs = [...byMushaf.keys()].sort((a, b) => {
            const ia = ORDER.indexOf(a), ib = ORDER.indexOf(b);
            if (ia === -1 && ib === -1) return a.localeCompare(b, 'ar');
            if (ia === -1) return 1;
            if (ib === -1) return -1;
            return ia - ib;
        });

        // Symbol pills — الهندي splits compound symbol into individual characters
        // IndoPak symbol string structure: ۟(06DF) + waqf_ruling_char + PUA_verse_num(0xF500–0xF699)
        // ۟ (06DF) = verse-end circle shape.  PUA chars = verse number glyph in IndoPak font.
        // These chars appear in IndoPak strings but carry no waqf ruling — filter from pills/meanings:
        const VERSE_END_MARKER = '\u06DF'; // ۟
        const HINDI_NON_WAQF = new Set([
            '\u06DC', // ۜ ARABIC SMALL HIGH SEEN — marks ص→س recitation variant (تجويد), not a waqf
            '\u06E0', // ۠ رأس الخمس — structural
            '\u06E1', // ۡ — not waqf
            '\u06E2', // ۢ — not waqf
            '\u06E4', // ۤ — not waqf
            '\u06E5', // ۥ — not waqf
            '\u06E6', // ۦ — not waqf
            '\u06ED', // ۭ — not waqf
        ]);
        const isPUA = ch => ch.codePointAt(0) >= 0xE000;

        function buildSymPills(symbols, isHindi, colorCls) {
            if (isHindi) {
                const chars = [...symbols];
                // Only actual waqf ruling chars get pills
                const waqfChars = chars.filter(ch =>
                    ch !== VERSE_END_MARKER && !HINDI_NON_WAQF.has(ch) && !isPUA(ch)
                );
                if (waqfChars.length === 0) return '';

                let html = '';
                // Render verse-end circle (۟ + PUA number glyph) dimmed, for context only
                const puaStr = chars.filter(isPUA).join('');
                if (chars.includes(VERSE_END_MARKER) || puaStr) {
                    const circleStr = (chars.includes(VERSE_END_MARKER) ? VERSE_END_MARKER : '') + puaStr;
                    html += `<span class="waqf-verse-circle" style="font-family:${indopakSymFont}">${circleStr}</span>`;
                }
                // Waqf ruling pills
                for (const ch of waqfChars) {
                    const info  = getWaqfInfo(ch, 'الهندي');
                    const title = (info.meaning && info.meaning !== ch)
                        ? ` title="${info.meaning.replace(/"/g, '&quot;')}"` : '';
                    html += `<span class="waqf-sym-pill waqf-sym-hindi waqf-mushaf-hindi"` +
                            ` style="font-family:${indopakSymFont}"${title}>${ch}</span>`;
                }
                return html;
            }
            // Normalize to the canonical Unicode glyph rendered by UthmanicHafs:
            // ۖ = صلى, ۗ = قلى, ۘ = م (لازم), ۚ = ج, ۙ = لا, ۛ = ع
            // This is how the symbol actually appears in the printed mushaf.
            const normalized = normalizeNonWarshWaqfText(symbols);
            const info   = getWaqfInfo(symbols);
            const title  = (info.meaning && info.meaning !== symbols)
                ? ` title="${info.meaning.replace(/"/g, '&quot;')}"` : '';
            return `<span class="waqf-sym-pill waqf-uthmanic ${colorCls}"${title}>${normalized}</span>`;
        }

        // Human-readable meaning text for a symbol string
        function buildMeaning(symbols, isHindi) {
            if (isHindi) {
                const parts = [...new Set([...symbols]
                    .filter(ch => ch !== VERSE_END_MARKER && !HINDI_NON_WAQF.has(ch) && !isPUA(ch))
                    .map(ch => {
                        const info = getWaqfInfo(ch, 'الهندي');
                        return (info.meaning && info.meaning !== ch) ? info.meaning : null;
                    }).filter(Boolean))];
                return parts.join(' · ');
            }
            const info = getWaqfInfo(symbols);
            return (info.meaning && info.meaning !== symbols) ? info.meaning : '';
        }

        const esc = s => (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;');

        const cardsHtml = sortedMushafs.map(ver => {
            const entryList = byMushaf.get(ver);
            const colorCls  = getMushafColorClass(ver);
            const isHindi   = /الهندي|هندي/.test(ver);

            const sortedEntries = [...entryList].sort((a, b) =>
                (Number(a.word_index) || (Number(a.token_index) + 1)) -
                (Number(b.word_index) || (Number(b.token_index) + 1))
            );

            const rowsHtml = sortedEntries.map(entry => {
                const wordText = getWordText(entry);
                const wIdx     = Number(entry.word_index) || (Number(entry.token_index) + 1);
                const sym      = entry.symbols || '';

                const symPills = buildSymPills(sym, isHindi, colorCls);
                // Skip rows that are purely verse-end markers with no waqf ruling
                if (isHindi && !symPills) return '';
                const meaning  = buildMeaning(sym, isHindi);

                // Other mushafs that also mark this same word position
                const sharedVers = [...(wordVersionsMap.get(wIdx) || [])].filter(v => v !== ver);
                const sharedHtml = sharedVers.length > 0
                    ? `<div class="waqf-entry-shared">${sharedVers.map(v =>
                        `<span class="waqf-shared-badge ${getMushafColorClass(v)}">${esc(v)}</span>`
                      ).join('')}</div>`
                    : '';

                return `<div class="waqf-entry-card">
                    <div class="waqf-entry-word">${esc(wordText)}</div>
                    <div class="waqf-entry-footer">
                        <span class="waqf-card-sym-wrap">${symPills}</span>
                        ${meaning ? `<span class="waqf-entry-lbl">${esc(meaning)}</span>` : ''}
                        ${sharedHtml}
                    </div>
                </div>`;
            }).filter(Boolean).join('');

            const countLabel = `${entryList.length} ${entryList.length === 1 ? 'علامة' : 'علامات'}`;
            return `<div class="waqf-mushaf-card ${colorCls}">
                <div class="waqf-card-header">
                    <span class="waqf-card-dot ${colorCls}">●</span>
                    <span class="waqf-card-name">${esc(ver)}</span>
                    <span class="waqf-card-count">${countLabel}</span>
                </div>
                <div class="waqf-card-body">${rowsHtml}</div>
            </div>`;
        }).join('');

        // ── Word view ────────────────────────────────────────────────────────
        // Table: rows = words that carry at least one waqf mark
        //        columns = الكلمة + one column per active mushaf
        function buildWordViewHtml() {
            const byWord = new Map();
            for (const e of entries) {
                const wIdx = Number(e.word_index) || (Number(e.token_index) + 1);
                if (!byWord.has(wIdx)) byWord.set(wIdx, []);
                byWord.get(wIdx).push(e);
            }

            const sortedWords = [...byWord.keys()].sort((a, b) => a - b);

            // Ordered list of mushafs actually present in this verse
            const activeMushafs = sortedMushafs; // already ORDER-sorted from above

            // Header row
            const headCols = activeMushafs.map(ver => {
                const colorCls = getMushafColorClass(ver);
                return `<th class="waqf-tbl-th ${colorCls}">${esc(ver)}</th>`;
            }).join('');

            // Body rows — one per word
            const bodyRows = sortedWords.map(wIdx => {
                const wordEntries = byWord.get(wIdx);
                const wordText    = getWordText(wordEntries[0]);

                // index version → entry for quick lookup
                const entryByVer = new Map(wordEntries.map(e => [e.version || '', e]));

                const cells = activeMushafs.map(ver => {
                    const entry    = entryByVer.get(ver);
                    const colorCls = getMushafColorClass(ver);
                    if (!entry) return `<td class="waqf-tbl-td waqf-tbl-empty">—</td>`;

                    const isHindi  = /الهندي|هندي/.test(ver);
                    const sym      = entry.symbols || '';
                    const symPills = buildSymPills(sym, isHindi, colorCls);
                    if (isHindi && !symPills) return `<td class="waqf-tbl-td waqf-tbl-empty">—</td>`;
                    const meaning  = buildMeaning(sym, isHindi);
                    return `<td class="waqf-tbl-td">
                        <span class="waqf-card-sym-wrap">${symPills}</span>
                        ${meaning ? `<div class="waqf-tbl-meaning">${esc(meaning)}</div>` : ''}
                    </td>`;
                }).join('');

                return `<tr>
                    <td class="waqf-tbl-word">${esc(wordText)}</td>
                    ${cells}
                </tr>`;
            }).filter(Boolean).join('');

            if (!bodyRows) return '<p class="waqf-panel-empty">لا توجد علامات وقف في هذه الآية</p>';

            return `<div class="waqf-tbl-wrap">
                <table class="waqf-tbl">
                    <thead><tr>
                        <th class="waqf-tbl-th waqf-tbl-word-hd">الكلمة</th>
                        ${headCols}
                    </tr></thead>
                    <tbody>${bodyRows}</tbody>
                </table>
            </div>`;
        }

        // ── Assemble panel ───────────────────────────────────────────────────
        const tabsHtml = `<div class="waqf-view-tabs">
            <button class="waqf-view-tab${waqfPanelView === 'mushaf' ? ' active' : ''}" data-waqf-view="mushaf">
                <i class="fas fa-layer-group"></i> عرض المصاحف
            </button>
            <button class="waqf-view-tab${waqfPanelView === 'word' ? ' active' : ''}" data-waqf-view="word">
                <i class="fas fa-align-right"></i> عرض الكلمات
            </button>
        </div>`;

        const viewHtml = waqfPanelView === 'word'
            ? `<div class="waqf-word-view">${buildWordViewHtml()}</div>`
            : `<div class="waqf-cards-grid">${cardsHtml}</div>`;

        container.innerHTML =
            `<div class="waqf-panel-header">` +
            `<div class="waqf-panel-title"><i class="fas fa-signs-post"></i> وقف هذه الآية</div>` +
            tabsHtml +
            `</div>` +
            viewHtml;
    }

    function renderShamarlyVerseWords(shamarlyPayload, segments) {
        const words = Array.isArray(shamarlyPayload?.words) ? shamarlyPayload.words : [];
        const filtered = filterWaqfByMode(shamarlyPayload?.waqf_symbols || []);
        const waqfByToken = buildWaqfByTokenIndex(filtered, words);
        const wordIndexToSegmentMap = new Map();
        const wordElements = [];
        mapSegmentsToWords(segments, wordIndexToSegmentMap);

        elements.quranTextContainer.innerHTML = '';

        words.forEach((word, index) => {
            const wordElement = createWordElement(word?.text || '', index, wordIndexToSegmentMap);
            // Render each word with the font of the page its (page-local) glyph came from.
            if (word?.glyph_page) {
                wordElement.style.fontFamily = `'${shamarlyFontName(word.glyph_page)}', 'UthmanicHafs', serif`;
            }
            const waqfSymbols = waqfByToken.get(index);
            if (waqfSymbols) {
                appendWaqfEntries(wordElement, waqfSymbols, shamarlyPayload?.mushaf_version || '');
            }
            wordElements[index] = wordElement;
            elements.quranTextContainer.appendChild(wordElement);
            elements.quranTextContainer.appendChild(document.createTextNode(' '));
        });

        attachHighlightHandler(wordElements, wordIndexToSegmentMap);
        refreshKhattRenderedWords();
    }

    function renderShamarlyVerseLines(shamarlyPayload) {
        const lines = Array.isArray(shamarlyPayload?.verse_lines) ? shamarlyPayload.verse_lines : [];
        const filteredSyms = filterWaqfByMode(shamarlyPayload?.waqf_symbols || []);
        const waqfByToken = buildWaqfByTokenIndex(filteredSyms, shamarlyPayload?.words || []);
        const verseWords = Array.isArray(shamarlyPayload?.words) ? shamarlyPayload.words : [];
        const coveredTokenIndexes = new Set();

        elements.quranTextContainer.innerHTML = '';
        lines.forEach((line) => {
            const lineEl = document.createElement('div');
            lineEl.className = 'shamarly-line';
            // Each verse line lives on one mushaf page; its words use that page's
            // page-local glyphs, so apply that page's font to the whole line.
            if (line.page_number) {
                lineEl.style.fontFamily = `'${shamarlyFontName(line.page_number)}', 'UthmanicHafs', serif`;
            }
            (line.words || []).forEach((word) => {
                const span = document.createElement('span');
                span.className = 'shamarly-word';
                span.textContent = word.text || '';
                const waqfSymbols = waqfByToken.get(word.token_index);
                if (waqfSymbols) {
                    appendWaqfEntries(span, waqfSymbols, shamarlyPayload?.mushaf_version || '');
                }
                if (Number.isInteger(word.token_index)) {
                    coveredTokenIndexes.add(word.token_index);
                }
                lineEl.appendChild(span);
            });
            elements.quranTextContainer.appendChild(lineEl);
        });

        // Fallback: ensure full ayah is visible when layout lines don't cover all tokens.
        const missingWords = verseWords
            .map((word, tokenIndex) => ({ word, tokenIndex }))
            .filter((entry) => !coveredTokenIndexes.has(entry.tokenIndex));

        if ((lines.length === 0 && verseWords.length > 0) || missingWords.length > 0) {
            const fallbackLine = document.createElement('div');
            fallbackLine.className = 'shamarly-line';
            const wordsToRender = lines.length === 0 ? verseWords.map((word, tokenIndex) => ({ word, tokenIndex })) : missingWords;

            wordsToRender.forEach(({ word, tokenIndex }) => {
                const span = document.createElement('span');
                span.className = 'shamarly-word';
                span.textContent = word?.text || '';
                const waqfSymbols = waqfByToken.get(tokenIndex);
                if (waqfSymbols) {
                    appendWaqfEntries(span, waqfSymbols, shamarlyPayload?.mushaf_version || '');
                }
                fallbackLine.appendChild(span);
            });

            elements.quranTextContainer.appendChild(fallbackLine);
        }

        detachHighlightHandler();
    }

    function renderShamarlyPage(shamarlyPayload) {
        const lines = Array.isArray(shamarlyPayload?.lines) ? shamarlyPayload.lines : [];
        elements.quranTextContainer.innerHTML = '';

        const frame = document.createElement('div');
        frame.className = 'shamarly-page-frame';

        lines.forEach((line) => {
            const lineEl = document.createElement('div');
            lineEl.className = 'shamarly-page-line';
            const lineType = (line.line_type || '').toString();
            if (lineType) {
                lineEl.classList.add(lineType.replace(/_/g, '-'));
            }
            if (line.contains_focus_ayah) {
                lineEl.classList.add('highlight');
            }

            const words = Array.isArray(line.words) ? line.words : [];
            if (words.length === 0 && line.raw_text) {
                lineEl.textContent = line.raw_text;
            } else {
                words.forEach((word) => {
                    const span = document.createElement('span');
                    span.className = 'shamarly-word';
                    span.textContent = word.text || '';
                    if (word.waqf_symbols) {
                        appendWaqfEntries(span, word.waqf_symbols, shamarlyPayload?.mushaf_version || '');
                    }
                    lineEl.appendChild(span);
                });
            }

            frame.appendChild(lineEl);
        });

        elements.quranTextContainer.appendChild(frame);

        if (shamarlyPayload?.page_number) {
            const indicator = document.createElement('div');
            indicator.className = 'shamarly-page-indicator';
            indicator.textContent = `صفحة ${shamarlyPayload.page_number}`;
            elements.quranTextContainer.appendChild(indicator);
        }

        detachHighlightHandler();
    }

    function buildWaqfByTokenIndex(waqfSymbols, words = []) {
        const map = new Map();
        if (!Array.isArray(waqfSymbols)) {
            return map;
        }

        const getWordText = (wordLike) => {
            if (typeof wordLike === 'string') {
                return wordLike;
            }
            if (wordLike && typeof wordLike === 'object') {
                return wordLike.text_original || wordLike.text || wordLike.word || '';
            }
            return '';
        };

        const hasTokenIndexes = waqfSymbols.some((entry) => entry && Number.isInteger(entry.token_index));

        // Strip whitespace AND all Arabic combining diacritics for comparison only.
        // Covers standard tashkeel, QPC/Warsh marks (U+06D6-U+06ED), and the
        // Arabic Extended-A combining marks (U+08D0-U+08FF) used by Digital Khatt
        // (e.g. U+08F1 tanwin instead of U+065E) — ensures base consonants match
        // regardless of which diacritic encoding the font uses.
        const normalize = (value) => (value || '')
            .replace(/\s+/g, '')
            .replace(/[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u08D0-\u08FF]/g, '');

        const hasWordIndexes = words.length > 0 && waqfSymbols.some((entry) => {
            const pos = Number(entry?.word_index);
            return Number.isInteger(pos) && pos > 0;
        });

        if (hasWordIndexes) {
            const wordPosToTokenIndex = new Map();
            let contentWordPos = 0;

            for (let i = 0; i < words.length; i++) {
                const token = getWordText(words[i]);
                if (normalize(token)) {
                    contentWordPos += 1;
                    if (!wordPosToTokenIndex.has(contentWordPos)) {
                        wordPosToTokenIndex.set(contentWordPos, i);
                    }
                }
            }

            waqfSymbols.forEach((entry) => {
                if (!entry || !entry.symbols) {
                    return;
                }
                const pos = Number(entry.word_index);
                if (!Number.isInteger(pos) || pos <= 0) {
                    return;
                }
                const tokenIndex = wordPosToTokenIndex.get(pos);
                if (Number.isInteger(tokenIndex)) {
                    if (!map.has(tokenIndex)) map.set(tokenIndex, []);
                    map.get(tokenIndex).push({ symbols: entry.symbols, version: entry.version || '' });
                }
            });

            if (map.size > 0) {
                return map;
            }
        }

        if (hasTokenIndexes) {
            waqfSymbols.forEach((entry) => {
                if (entry && Number.isInteger(entry.token_index) && entry.symbols) {
                    if (!map.has(entry.token_index)) map.set(entry.token_index, []);
                    map.get(entry.token_index).push({ symbols: entry.symbols, version: entry.version || '' });
                }
            });
            if (map.size > 0) {
                return map;
            }
        }

        let searchStart = 0;

        waqfSymbols.forEach((entry) => {
            if (!entry || !entry.symbols) {
                return;
            }

            const targetWord = normalize(entry.clean_token || entry.original_token || entry.word || '');
            if (!targetWord) {
                return;
            }

            let foundIndex = -1;
            for (let i = searchStart; i < words.length; i++) {
                if (normalize(getWordText(words[i])) === targetWord) {
                    foundIndex = i;
                    break;
                }
            }

            if (foundIndex === -1) {
                for (let i = 0; i < words.length; i++) {
                    if (normalize(getWordText(words[i])) === targetWord) {
                        foundIndex = i;
                        break;
                    }
                }
            }

            if (foundIndex >= 0) {
                if (!map.has(foundIndex)) map.set(foundIndex, []);
                map.get(foundIndex).push({ symbols: entry.symbols, version: entry.version || '' });
                searchStart = foundIndex + 1;
            }
        });
        return map;
    }

    function isWarshMushafVersion(mushafVersion = '') {
        return /ورش|warsh/i.test((mushafVersion || '').toString());
    }

    function normalizeNonWarshWaqfText(raw) {
        return raw
            .split(/[،,]/)
            .map((token) => token.replace(/\s+/g, '').trim())
            .filter(Boolean)
            .map((token) => {
                const waqfGlyphMap = {
                    'م': 'ۘ',
                    'قلى': 'ۗ',
                    'قلي': 'ۗ',
                    'ق': 'ۗ',
                    'صلى': 'ۖ',
                    'صلي': 'ۖ',
                    'ص': 'ۖ',
                    'ج': 'ۚ',
                    'لا': 'ۙ',
                    'ع': 'ۛ',
                    // Standard waqf combining marks — pass through
                    'ۘ': 'ۘ', 'ۗ': 'ۗ', 'ۖ': 'ۖ', 'ۚ': 'ۚ', 'ۙ': 'ۙ', 'ۛ': 'ۛ', 'ۜ': 'ۜ',
                    // IndoPak / Pakistani mushaf symbols — pass through as-is
                    'ؕ': 'ؕ',  // U+0615  mandatory stop (لازم)
                    'ؗ': 'ؗ',  // U+0617  zain marker
                    'ؔ': 'ؔ',  // U+0614  takhallus
                    '۪': '۪',  // U+06EA  empty centre low stop
                    '۫': '۫',  // U+06EB  empty centre high stop
                    '۬': '۬',  // U+06EC  rounded high stop
                };
                return waqfGlyphMap[token] || token;
            })
            .join('');
    }

    // Normalise Warsh waqf raw DB values:
    //   ر  → ۜ (U+06DC) رأس آية — verse-end pause
    //   ص  → ۖ (U+06D6) وصل أولى — better to continue
    function normalizeWarshWaqfText(raw) {
        if (!raw || !raw.trim()) return '';
        return raw.split(/[،,]/)
            .map(t => t.trim())
            .filter(Boolean)
            .map(t => {
                if (t === 'ر' || t === '\u06DC') return '\u06DC'; // رأس آية
                if (t === 'ص' || t === '\u06D6') return '\u06D6'; // وصل أولى
                return ''; // drop unknown tokens \u2014 do not mislabel as \u0631\u0623\u0633 \u0622\u064A\u0629
            })
            .filter(Boolean)
            .join('');
    }

    // ── Waqf symbol meanings (display only, no color here) ─────────────────
    // Standard waqf meanings (Madina / Hafs / Azhar / Husary etc.)
    const WAQF_INFO = {
        'م':   { meaning: 'وقف لازم — الوقف واجب' },
        'قلى': { meaning: 'قلى — الأفضل الوقف' },
        'قلي': { meaning: 'قلى — الأفضل الوقف' },
        'ق':   { meaning: 'قلى — الأفضل الوقف' },
        'ر':   { meaning: 'راجح — الأفضل الوقف' },
        'ص':   { meaning: 'صلى — الأفضل الوصل' },
        'صه':  { meaning: 'صه — وقف تام (مصحف ورش)' },
        'صلى': { meaning: 'صلى — الأفضل الوصل' },
        'صلي': { meaning: 'صلى — الأفضل الوصل' },
        'ج':   { meaning: 'جائز — يجوز الوقف والوصل' },
        'لا':  { meaning: 'لا وقف — يجب الوصل' },
        'ع':   { meaning: 'معانقة — إذا وقفت على أحدهما لا تقف على الآخر' },
        '\u21BA':   { meaning: 'وقف إعادة — ارجع للبداية' },
        '\u25B6':   { meaning: 'بداية الإعادة' },
        '\u06DC': { meaning: 'رأس آية — نهاية الآية وموضع الوقف (مصحف ورش)' },
        // Standard Unicode waqf glyphs (after normalisation)
        '\u06D6': { meaning: 'صلى — الأفضل الوصل' },
        '\u06D7': { meaning: 'قلى — الأفضل الوقف' },
        '\u06D8': { meaning: 'م — وقف لازم' },
        '\u06D9': { meaning: 'لا — لا يجوز الوقف' },
        '\u06DA': { meaning: 'ج — جائز الوقف والوصل' },
        '\u06DB': { meaning: 'ع — وقف معانقة' },
    };

    // IndoPak-specific overrides — same letters/glyphs have different rulings.
    const WAQF_INFO_HINDI = {
        'م':       { meaning: 'وقف لازم (مصحف هندي)' },
        'ص':       { meaning: 'مرخّص لضرورة (مصحف هندي)' },
        'ط':       { meaning: 'مطلق — رمز خاص بالمصحف الهندي' },
        'ز':       { meaning: 'مجوَّز — رمز خاص بالمصحف الهندي' },
        'ج':       { meaning: 'ج — جائز الوقف والوصل (مصحف هندي)' },
        'لا':      { meaning: 'لا — لا يجوز الوقف (مصحف هندي)' },
        '\u0615': { meaning: 'وقف مطلق (مصحف هندي/باكستاني)' },
        '\u0617': { meaning: 'وقف مجوز لوجه (مصحف هندي)' },
        '\u06D6': { meaning: 'صلى — مرخّص لضرورة (مصحف هندي)' },
        '\u06D7': { meaning: 'قلى — الأفضل الوقف (مصحف هندي)' },
        '\u06D8': { meaning: 'م — وقف لازم (مصحف هندي)' },
        '\u06D9': { meaning: 'لا — لا يجوز الوقف (مصحف هندي)' },
        '\u06DA': { meaning: 'ج — جائز الوقف والوصل (مصحف هندي)' },
        '\u06DB': { meaning: 'ع — وقف معانقة (مصحف هندي)' },
        '\u0614': { meaning: 'قف — قف ولا تصل (مصحف هندي/باكستاني)' },
        '\u06DF': { meaning: 'رأس الآية أو رمز الوقف الكامل (مصحف هندي)' },
        '\u06E0': { meaning: 'رأس الخمس (مصحف هندي)' },
        '\u06EA': { meaning: 'وقف تحتي (مصحف هندي)' },
        '\u06EB': { meaning: 'وقف فوقي (مصحف هندي)' },
        '\u06EC': { meaning: 'وقف دائري (مصحف هندي)' },
    };

    function getWaqfInfo(rawSymbol, version = '') {
        const key = (rawSymbol || '').trim();
        if (version === 'الهندي' && WAQF_INFO_HINDI[key]) return WAQF_INFO_HINDI[key];
        return WAQF_INFO[key] || WAQF_INFO_HINDI[key] || { meaning: key };
    }

    // kept for backward-compat callers
    function getWaqfMeaning(rawSymbol) {
        return getWaqfInfo(rawSymbol).meaning;
    }

    // MUSHAF_COLOR_MAP and getMushafColorClass defined earlier near loadMushafVersions

    function getWaqfDisplayData(waqfText, mushafVersionOverride = '') {
        const raw = (waqfText || '').toString().trim();
        if (!raw) return null;

        const version = mushafVersionOverride || '';
        const isWarsh = isWarshMushafVersion(version);

        if (isWarsh) {
            // Normalize to proper Unicode waqf codepoints, then UthmanicWarsh font renders them correctly
            const normalized = normalizeWarshWaqfText(raw);
            return { text: normalized, extraClass: 'waqf-warsh', title: raw };
        }

        const normalized = normalizeNonWarshWaqfText(raw);
        // Suppress repeat-only markers (↺ ▶) — these are recording cues, not Quranic stop signs
        if (/^[\u21BA\u25B6]+$/.test(normalized)) return null;
        return {
            text: normalized,
            extraClass: '',
            title: raw
        };
    }

    function getOrCreateWaqfStack(wordEl) {
        let stack = wordEl.querySelector(':scope > .waqf-stack');
        if (!stack) {
            stack = document.createElement('span');
            stack.className = 'waqf-stack';
            wordEl.prepend(stack);
        }
        return stack;
    }

    function appendWaqfEntries(container, entriesOrText, fallbackVersion = '') {
        if (!entriesOrText) return;
        const entries = Array.isArray(entriesOrText)
            ? entriesOrText
            : [{ symbols: entriesOrText, version: fallbackVersion }];
        entries.forEach((e) => appendWaqfSymbol(container, e.symbols || e, e.version || fallbackVersion));
    }

    function appendWaqfSymbol(container, waqfText, mushafVersionOverride = '') {
        const displayData = getWaqfDisplayData(waqfText, mushafVersionOverride);
        if (!displayData) return;

        const stack = getOrCreateWaqfStack(container);

        // Color is per-mushaf; apply any extraClass (e.g. waqf-warsh font)
        const colorClass = getMushafColorClass(mushafVersionOverride);
        const extra = [colorClass];
        if (displayData.extraClass) extra.push(displayData.extraClass);
        const className = 'waqf-symbol ' + extra.join(' ');

        const versionLabel = mushafVersionOverride ? `مصحف: ${mushafVersionOverride}` : '';

        // Split multi-character text into individual symbols so they each get
        // their own <span>, preventing Arabic combining marks from overlapping.
        // For الهندي: strip verse-end circle (۟ U+06DF) and PUA font-ligature glyphs
        // (U+E000–U+F8FF) — these are structural font chars embedded by the font
        // renderer, not actual waqf rulings, and must never appear as waqf overlays.
        const _isHindi = mushafVersionOverride === 'الهندي';
        const symbols = [...displayData.text].filter(ch => {
            if (!ch.trim()) return false;
            if (_isHindi) {
                const cp = ch.codePointAt(0);
                if (ch === '\u06DF') return false;            // ۟ verse-end circle
                if (ch === '\u06DC') return false;            // ۜ small high seen — تجويد, not waqf
                if (cp >= 0xE000 && cp <= 0xF8FF) return false; // PUA glyph
            }
            return true;
        });
        if (symbols.length === 0) return;

        for (const sym of symbols) {
            const symbolSpan = document.createElement('span');
            symbolSpan.className = className;
            if (mushafVersionOverride) symbolSpan.dataset.version = mushafVersionOverride;
            symbolSpan.textContent = sym;

            // Tooltip: "مصحف: الأزهر | ج — جائز"
            const info = getWaqfInfo(sym.trim(), mushafVersionOverride);
            const symbolLabel = info.meaning || displayData.title.trim();
            symbolSpan.title = [versionLabel, symbolLabel].filter(Boolean).join(' | ');

            if (_isHindi) {
                // الهندي symbols go into their own inner column group so the
                // outer row-stack of other mushafs is not affected
                let hindiGroup = stack.querySelector(':scope > .waqf-hindi-group');
                if (!hindiGroup) {
                    hindiGroup = document.createElement('span');
                    hindiGroup.className = 'waqf-hindi-group';
                    stack.appendChild(hindiGroup);
                }
                hindiGroup.appendChild(symbolSpan);
            } else {
                stack.appendChild(symbolSpan);
            }
        }
    }
    function stripEmbeddedWaqf(text) {
        // Only strip the 7 actual waqf stop marks: U+06D6–U+06DC (ۖۗۘۙۚۛۜ)
        return (text || '').replace(/[\u06D6-\u06DC]/g, '');
    }

    function getCurrentWaqfMode() {
        return document.body.dataset.waqfMode || 'both';
    }

    function setWaqfMode(mode) {
        const validModes = ['both', 'original', 'selected', 'none'];
        if (!validModes.includes(mode)) mode = 'both';

        document.body.dataset.waqfMode = mode;
        localStorage.setItem('quranApp_waqfMode', mode);

        // Update active button highlight
        if (elements.waqfModeControl) {
            elements.waqfModeControl.querySelectorAll('.waqf-mode-btn').forEach((btn) => {
                btn.classList.toggle('active', btn.dataset.mode === mode);
            });
        }

        // Trigger a full re-render so the verse text variant and overlay symbols
        // both reflect the new mode. Skip if we're still booting (no ayah loaded).
        if (currentAyahData && elements.ayahSelect && elements.ayahSelect.value) {
            loadQuranData();
        }
    }

    function detachHighlightHandler() {
        if (elements.audioElement.timeUpdateHandler) {
            elements.audioElement.removeEventListener('timeupdate', elements.audioElement.timeUpdateHandler);
            elements.audioElement.timeUpdateHandler = null;
        }
    }

    function attachHighlightHandler(wordElements, wordIndexToSegmentMap) {
        detachHighlightHandler();

        let lastHighlightTime = 0;
        const highlightThrottle = 100;
        elements.audioElement.timeUpdateHandler = () => {
            const now = Date.now();
            if (now - lastHighlightTime >= highlightThrottle) {
                highlightWords(wordElements, wordIndexToSegmentMap);
                lastHighlightTime = now;
            }
        };
        elements.audioElement.addEventListener('timeupdate', elements.audioElement.timeUpdateHandler);
    }

    function displayTransliteration(data) {
        if (elements.transliterationContainer) {
            elements.transliterationContainer.innerHTML = data?.t || 'No transliteration available';
        }
    }

    function displayTafseers(tafseers) {
        if (elements.tafseerContainer) {
            elements.tafseerContainer.innerHTML = '';
            const tafseerEntries = Object.entries(tafseers);
            if (tafseerEntries.length > 0) {
                const selectElement = document.getElementById('tafseer-select');
                const tafseerTextElement = document.getElementById('tafseer-text');

                const tafseerArray = Object.keys(tafseers).map(tafseerName => ({
                   value: tafseerName,
                   text: tafseerName
                }));
                populateSelectOptions(tafseerArray, selectElement, 'value', 'text');

                const previouslySelectedTafseer = localStorage.getItem('selectedTafseer');
                if (previouslySelectedTafseer && tafseers[previouslySelectedTafseer]) {
                    selectElement.value = previouslySelectedTafseer;
                }

                // Remove old listener to prevent memory leak
                if (selectElement._tafseerChangeHandler) {
                    selectElement.removeEventListener('change', selectElement._tafseerChangeHandler);
                }

                selectElement._tafseerChangeHandler = () => {
                    const selectedValue = selectElement.value;
                    const selectedTafseer = tafseers[selectedValue] || { text: 'No tafseer available' };
                    tafseerTextElement.innerHTML = selectedTafseer.text;
                    localStorage.setItem('selectedTafseer', selectedValue);
                };

                selectElement.addEventListener('change', selectElement._tafseerChangeHandler);
                selectElement.dispatchEvent(new Event('change'));
            } else {
                elements.tafseerContainer.innerHTML = 'No tafseer available';
            }
        }
    }

    function displayWordMeanings(wordMeanings, _verseText) {
        if (!elements.wordMeaningContainer) return;
        elements.wordMeaningContainer.innerHTML = '';
        // Accept ordered array [{word, meaning}] or legacy dict {word: meaning}
        const entries = Array.isArray(wordMeanings)
            ? wordMeanings
            : Object.entries(wordMeanings || {}).map(([word, meaning]) => ({ word, meaning }));
        if (!entries.length) {
            elements.wordMeaningContainer.innerHTML = '<p class="no-meanings">لا توجد معاني متاحة لهذه الآية</p>';
            return;
        }
        const dl = document.createElement('dl');
        dl.className = 'word-meanings-list';
        entries.forEach(({ word, meaning }) => {
            if (!word || !meaning) return;
            const dt = document.createElement('dt');
            dt.textContent = word;
            const dd = document.createElement('dd');
            dd.textContent = meaning;
            dl.appendChild(dt);
            dl.appendChild(dd);
        });
        elements.wordMeaningContainer.appendChild(dl);
    }

    function toggleTransliteration() {
        const transliterationContainer = document.getElementById('transliteration-container');
        transliterationContainer.style.display = transliterationContainer.style.display === 'none' ? 'block' : 'none';
        updateTransliterationButton();
    }

    async function toggleTafseer() {
        const tafseerContainer = document.getElementById('tafseer-container');
        const isHidden = tafseerContainer.style.display === 'none';
        tafseerContainer.style.display = isHidden ? 'block' : 'none';
        updateTafseerButton();
        if (isHidden) {
            const surah = elements.surahSelect.value;
            const ayah = elements.ayahSelect.value;
            if (surah && ayah) {
                await fetchAndDisplayTafseer(surah, ayah);
            }
        }
    }

    async function fetchAndDisplayTafseer(surahNumber, ayahNumber) {
        // Return cached result if already fetched for this ayah
        if (currentAyahData?.surah_number === parseInt(surahNumber) &&
            currentAyahData?.ayah_number === parseInt(ayahNumber) &&
            currentAyahData?.tafseer && Object.keys(currentAyahData.tafseer).length > 0) {
            displayTafseers(currentAyahData.tafseer);
            return;
        }
        try {
            const data = await fetchData(`/api/tafseer/${surahNumber}/${ayahNumber}`);
            if (currentAyahData) {
                currentAyahData.tafseer = data;
            }
            displayTafseers(data);
        } catch (e) {
            console.error('Error loading tafseer:', e);
        }
    }

    function isKhattFontActive() {
        return document.body.dataset.fontType === 'digital_khatt' || document.body.dataset.fontType === 'old_madina';
    }

    function isDigitalKhattFontActive() {
        return document.body.dataset.fontType === 'digital_khatt';
    }

    function getCurrentKhattJustifyValue() {
        const raw = elements.khattJustifySlider?.value ?? localStorage.getItem('quranApp_khattJustify') ?? '50';
        const parsed = parseInt(raw, 10);
        return Number.isFinite(parsed) ? Math.max(0, Math.min(100, parsed)) : 50;
    }

    function getKhattFeatureSequence() {
        const features = [];
        for (let level = 1; level <= 5; level += 1) {
            for (const type of ['jt', 'dc', 'kt']) {
                features.push(`${type}0${level}`);
            }
        }
        return features;
    }

    function getKhattFeatureSettings(strength) {
        const normalizedStrength = Math.max(0, Math.min(100, Number(strength) || 0));
        if (!isKhattFontActive() || normalizedStrength <= 0) return '';

        if (document.body.dataset.fontType === 'digital_khatt') {
            const digitalKhattLevels = [
                `'jalt' 1`,
                `'jalt' 1, 'cv02' 1`,
                `'jalt' 1, 'cv01' 1`,
                `'jalt' 1, 'cv01' 1, 'cv02' 1`
            ];
            const level = Math.min(
                digitalKhattLevels.length,
                Math.max(1, Math.ceil((normalizedStrength / 100) * digitalKhattLevels.length))
            );
            return digitalKhattLevels[level - 1] || '';
        }

        const featureSequence = getKhattFeatureSequence();
        const featureCount = Math.round((normalizedStrength / 100) * featureSequence.length);
        if (featureCount <= 0) return '';

        return featureSequence
            .slice(0, featureCount)
            .map((feature) => `'${feature}'`)
            .join(',');
    }

    function getDisplayedWordText(rawText) {
        return rawText || '';
    }

    function applyTextKhattWord(baseEl, rawText, featureSettings) {
        baseEl.textContent = getDisplayedWordText(rawText);
        baseEl.style.fontFeatureSettings = featureSettings || null;
        baseEl.dataset.khattRenderMode = 'text';
    }

    function refreshKhattRenderedWords() {
        const mode = getCurrentWaqfMode();
        const renderVersion = ++khattRenderVersion;
        const strength = getCurrentKhattJustifyValue();
        const featureSettings = getKhattFeatureSettings(strength);
        const wordItems = [];
        document.querySelectorAll('#quran-text .word-token').forEach((wordEl) => {
            const rawText = (mode === 'selected' || mode === 'none')
                ? (wordEl.dataset.textClean || '')
                : (wordEl.dataset.textOriginal || wordEl.dataset.textClean || '');
            const baseEl = wordEl.querySelector(':scope > .word-content > .word-base');
            if (baseEl) {
                wordItems.push({ wordEl, baseEl, rawText });
            }
        });

        wordItems.forEach((item) => {
            applyTextKhattWord(item.baseEl, item.rawText, featureSettings);
        });

        void applyVisibleTajweedToVerseText(wordItems, featureSettings, renderVersion);
    }

    async function maybeRefreshTafseer(surahNumber, ayahNumber) {
        const tafseerContainer = document.getElementById('tafseer-container');
        if (tafseerContainer && tafseerContainer.style.display !== 'none') {
            await fetchAndDisplayTafseer(surahNumber, ayahNumber);
        } else {
            displayTafseers({});
        }
    }

    async function toggleEerab() {
        const eerabContainer = document.getElementById('eerab-container');
        if (!eerabContainer) return;
        const isHidden = eerabContainer.style.display === 'none';
        eerabContainer.style.display = isHidden ? 'block' : 'none';
        updateEerabButton();
        if (isHidden) {
            const surah = elements.surahSelect.value;
            const ayah = elements.ayahSelect.value;
            if (surah && ayah) {
                await fetchAndDisplayEerab(surah, ayah);
            }
        }
    }

    async function fetchAndDisplayEerab(surahNumber, ayahNumber) {
        if (currentAyahData?.surah_number === parseInt(surahNumber) &&
            currentAyahData?.ayah_number === parseInt(ayahNumber) &&
            currentAyahData?.eerab) {
            displayEerab(currentAyahData.eerab);
            return;
        }
        try {
            const data = await fetchData(`/api/eerab/${surahNumber}/${ayahNumber}`);
            if (currentAyahData) {
                currentAyahData.eerab = data;
            }
            displayEerab(data);
        } catch (e) {
            console.error('Error loading eerab:', e);
        }
    }

    async function maybeRefreshEerab(surahNumber, ayahNumber) {
        const eerabContainer = document.getElementById('eerab-container');
        if (eerabContainer && eerabContainer.style.display !== 'none') {
            await fetchAndDisplayEerab(surahNumber, ayahNumber);
        }
    }

    function displayEerab(data) {
        const eerabTextEl = document.getElementById('eerab-text');
        if (!eerabTextEl) return;
        const content = data?.content || '';
        if (!content) {
            eerabTextEl.innerHTML = '<p class="eerab-empty">لا يوجد إعراب متاح لهذه الآية.</p>';
            return;
        }
        const lines = content.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
        const html = lines.map(line => {
            if (line.startsWith('{') && line.includes('}')) {
                return `<p class="eerab-ayah-header">${line}</p>`;
            }
            const colonIdx = line.indexOf(':');
            if (colonIdx > 0) {
                const word = line.substring(0, colonIdx).trim();
                const analysis = line.substring(colonIdx + 1).trim();
                return `<div class="eerab-entry"><span class="eerab-word">${word}</span><span class="eerab-colon">:</span> <span class="eerab-analysis">${analysis}</span></div>`;
            }
            return `<p class="eerab-line">${line}</p>`;
        }).join('');
        eerabTextEl.innerHTML = html;
    }

    function updateEerabButton() {
        const eerabButton = document.getElementById('show-eerab');
        const eerabContainer = document.getElementById('eerab-container');
        if (!eerabButton || !eerabContainer) return;
        eerabButton.textContent = eerabContainer.style.display === 'none' ? 'الإعراب' : 'إخفاء الإعراب';
    }

    // ── Tajweed ─────────────────────────────────────────────────────────────────────────
    // JS-side cache: verse_key → html string
    const _tajweedHtmlCache = {};

    // The tajweed source (cpfair/quran-tajweed) is written in a Tanzil/Imlaei
    // orthography that diverges from our QPC Hafs display text in many systematic
    // ways: standalone hamza+alef ءَا vs أٓ, final ى vs ي, omitted sukun, different
    // tanwin marks, etc. We must therefore NOT inject the source text — instead we
    // OVERLAY the tajweed colours onto the unchanged QPC display characters by
    // aligning the two strings. Stripping the resulting tags always yields the
    // original display word, so orthography is preserved exactly.

    // Arabic combining (non-spacing) marks: harakat, dagger-alef (U+0670),
    // maddah/hamza-above (U+0653/U+0654), Quranic annotation marks, etc.
    function _isCombiningMark(cp) {
        return (cp >= 0x064B && cp <= 0x065F) || cp === 0x0670 ||
               (cp >= 0x06D6 && cp <= 0x06ED) || (cp >= 0x0610 && cp <= 0x061A) ||
               (cp >= 0x0653 && cp <= 0x0658) || cp === 0x06E5 || cp === 0x06E6;
    }

    // Skeleton class for alignment: fold orthographic variants so equivalent
    // letters match across the two spellings (alef/hamza family, ya/alef-maqsura,
    // ta-marbuta).
    function _alignSkeleton(ch) {
        const cp = ch.codePointAt(0);
        if (cp === 0x0622 || cp === 0x0623 || cp === 0x0625 || cp === 0x0627 ||
            cp === 0x0671 || cp === 0x0621 || cp === 0x0624 || cp === 0x0626) return 'A';
        if (cp === 0x0649 || cp === 0x064A) return 'Y';
        if (cp === 0x0629) return 'H';
        return ch;
    }

    // Needleman–Wunsch alignment. Returns, for each display-char index, the source
    // index it aligns to (or -1 for a display-only insertion such as an ornament).
    function _alignDisplayToSource(srcChars, dispChars) {
        const n = srcChars.length, m = dispChars.length;
        const dp = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
        for (let i = 1; i <= n; i++) dp[i][0] = dp[i - 1][0] - 1;
        for (let j = 1; j <= m; j++) dp[0][j] = dp[0][j - 1] - 1;
        for (let i = 1; i <= n; i++) {
            for (let j = 1; j <= m; j++) {
                const sc = _alignSkeleton(srcChars[i - 1]) === _alignSkeleton(dispChars[j - 1]) ? 2 : -1;
                dp[i][j] = Math.max(dp[i - 1][j - 1] + sc, dp[i - 1][j] - 1, dp[i][j - 1] - 1);
            }
        }
        const res = new Array(m).fill(-1);
        let i = n, j = m;
        while (i > 0 && j > 0) {
            const sc = _alignSkeleton(srcChars[i - 1]) === _alignSkeleton(dispChars[j - 1]) ? 2 : -1;
            if (dp[i][j] === dp[i - 1][j - 1] + sc) { res[j - 1] = i - 1; i--; j--; }
            else if (dp[i][j] === dp[i - 1][j] - 1) { i--; }
            else { j--; }
        }
        return res;
    }

    /**
     * Overlay tajweed colours onto the QPC display word.
     * @param {string} dispWord  the exact characters currently displayed
     * @param {{text:string,cls:string}[]} parts  the source word's coloured runs
     * Returns HTML whose text content equals dispWord (orthography untouched).
     */
    function overlayTajweedOnDisplay(dispWord, parts) {
        const srcChars = [];
        const srcCls = [];
        for (const p of (parts || [])) {
            for (const ch of p.text) { srcChars.push(ch); srcCls.push(p.cls || ''); }
        }
        const dispChars = [...dispWord];
        const dcls = new Array(dispChars.length).fill('');
        if (srcChars.length && srcCls.some(c => c)) {
            const amap = _alignDisplayToSource(srcChars, dispChars);
            for (let j = 0; j < dispChars.length; j++) {
                const si = amap[j];
                if (si >= 0) dcls[j] = srcCls[si];
            }
            // Cluster unification: a base letter and the combining marks that sit on
            // it must share one colour, otherwise a mark-only span (e.g. the مدّ
            // dagger-alef ٰ in ذَٰلِكَ) shapes in isolation and its colour vanishes.
            // Colouring the whole grapheme cluster is also how printed tajweed
            // mushafs render the elongated letter.
            let i = 0;
            while (i < dispChars.length) {
                const start = i; i++;
                while (i < dispChars.length && _isCombiningMark(dispChars[i].codePointAt(0))) i++;
                let chosen = '';
                for (let k = start; k < i; k++) { if (dcls[k]) { chosen = dcls[k]; break; } }
                for (let k = start; k < i; k++) dcls[k] = chosen;
            }
        }
        const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        let html = '', cur = null, buf = '';
        for (let j = 0; j < dispChars.length; j++) {
            const cl = dcls[j];
            if (cl !== cur) {
                if (buf) html += cur ? `<tajweed class="${cur}">${esc(buf)}</tajweed>` : esc(buf);
                buf = ''; cur = cl;
            }
            buf += dispChars[j];
        }
        if (buf) html += cur ? `<tajweed class="${cur}">${esc(buf)}</tajweed>` : esc(buf);
        return html;
    }

    function isTajweedEnabled() {
        return document.body.dataset.tajweedEnabled === 'true';
    }

    async function getTajweedHtml(surahNumber, ayahNumber) {
        const verseKey = `${surahNumber}:${ayahNumber}`;
        if (_tajweedHtmlCache[verseKey]) {
            return _tajweedHtmlCache[verseKey];
        }
        const data = await fetchData(`/api/tajweed/${surahNumber}/${ayahNumber}`);
        const html = data?.html || '';
        _tajweedHtmlCache[verseKey] = html;
        return html;
    }

    function getNormalizedTajweedHtml(html) {
        return _reclassifyMunfasilInHtml(
            (html || '').replace(/<span[^>]*class=["']?end["']?[^>]*>.*?<\/span>/gi, '').trim()
        );
    }

    async function applyVisibleTajweedToVerseText(wordItems, featureSettings, renderVersion) {
        if (!isTajweedEnabled() || !wordItems.length) return;
        // الشمرلي renders page-local glyphs, not real letters, so per-letter
        // tajweed spans don't apply — skip coloring entirely in that mode.
        if (document.body.dataset.fontType === 'shamarly') return;

        const surahNumber = elements.surahSelect?.value;
        const ayahNumber = elements.ayahSelect?.value;
        if (!surahNumber || !ayahNumber) return;

        try {
            const html = await getTajweedHtml(surahNumber, ayahNumber);
            if (renderVersion !== khattRenderVersion || !isTajweedEnabled()) return;

            const tajweedWords = parseTajweedIntoWords(getNormalizedTajweedHtml(html));
            const waqfMode = getCurrentWaqfMode();
            const hideEmbeddedWaqf = waqfMode === 'selected' || waqfMode === 'none';
            const contentWordItems = wordItems.filter(({ wordEl }) => {
                const cleanText = (wordEl.dataset.textClean || '').trim();
                return /[\u0621-\u064A]/.test(cleanText);
            });

            if (tajweedWords.length !== contentWordItems.length) {
                return;
            }

            contentWordItems.forEach((item, index) => {
                // Overlay colours onto the unchanged QPC display word (mode-aware:
                // rawText already has waqf stripped in selected/none). Ornaments,
                // waqf marks and verse numbers align to nothing in the source and
                // stay uncoloured — no peeling needed. Stripping the emitted tags
                // always reproduces the display word, so orthography never changes.
                let dispWord = item.rawText || item.wordEl.dataset.textClean || '';
                if (hideEmbeddedWaqf) dispWord = stripEmbeddedWaqf(dispWord);
                item.baseEl.innerHTML = overlayTajweedOnDisplay(dispWord, tajweedWords[index].parts);
                item.baseEl.style.fontFeatureSettings = featureSettings || null;
                item.baseEl.dataset.khattRenderMode = 'text-tajweed';
            });
        } catch (error) {
            console.error('Failed to apply tajweed to verse text:', error);
        }
    }

    /**
     * Parse the tajweed HTML (served locally from /api/tajweed) into word segments.
     *
     * A rule sometimes wraps text that spans word boundaries inside one tag,
     * e.g. <tajweed class=idgham_ghunnah>ةٌ و</tajweed>  (the space is INSIDE).
     * We flatten the DOM to a linear token stream first, then split on spaces.
     *
     * Returns [{html: string, rules: string[]}]
     */
    function parseTajweedIntoWords(html) {
        const tmp = document.createElement('div');
        tmp.innerHTML = html;

        // Step 1: flatten into tokens [{text, cls}]
        // cls is the tajweed rule that wraps this text chunk ('' = plain text)
        const tokens = [];
        for (const node of tmp.childNodes) {
            if (node.nodeType === 3 /* TEXT_NODE */) {
                const t = node.textContent;
                if (t) tokens.push({ text: t, cls: '' });
            } else if (node.nodeType === 1 /* ELEMENT_NODE */) {
                const cls = (node.getAttribute('class') || '').trim();
                if (cls === 'end') continue; // skip verse-number marker
                const t = node.textContent;
                if (t) tokens.push({ text: t, cls });
            }
        }

        // Step 2: split each token on spaces to get sub-tokens
        // [{text: string (no spaces), cls: string, boundary: bool}]
        // boundary=true means "word ends AFTER this sub-token"
        const subTokens = [];
        for (const { text, cls } of tokens) {
            const parts = text.split(' ');
            for (let i = 0; i < parts.length; i++) {
                const isLast = i === parts.length - 1;
                if (parts[i]) {
                    subTokens.push({ text: parts[i], cls, boundary: !isLast });
                } else if (!isLast) {
                    // empty string before boundary = boundary only
                    subTokens.push({ text: '', cls, boundary: true });
                }
            }
        }

        // Step 3: group sub-tokens into words
        const segments = [];
        let segParts = []; // [{text, cls}]
        let segRules = new Set();

        const flush = () => {
            const combined = segParts.map(p => p.text).join('');
            if (combined.trim()) {
                // Detect مد جائز منفصل: the quran.com API mislabels it as madda_obligatory.
                // When the madda_obligatory tag ends the word with NO Arabic hamza (ء/أ/إ/ؤ/ئ)
                // in or after the tagged text, the hamza belongs to the next word → منفصل.
                const _hamzaRe = /[\u0621\u0623\u0624\u0625\u0626]/;
                let finalParts = segParts;
                if (segRules.has('madda_obligatory')) {
                    const madIdx = segParts.map(p => p.cls).lastIndexOf('madda_obligatory');
                    const textInMad    = segParts[madIdx]?.text || '';
                    const textAfterMad = segParts.slice(madIdx + 1).map(p => p.text).join('');
                    if (!_hamzaRe.test(textInMad) && !_hamzaRe.test(textAfterMad)) {
                        // No hamza found in same word → reclassify as مد جائز منفصل
                        finalParts = segParts.map(p =>
                            p.cls === 'madda_obligatory' ? { ...p, cls: 'madda_munfasil' } : p
                        );
                        segRules.delete('madda_obligatory');
                        segRules.add('madda_munfasil');
                    }
                }
                // Emit the source word's coloured runs as `parts`; the renderer
                // (overlayTajweedOnDisplay) aligns these onto the QPC display word
                // rather than substituting the source text. `html` is kept only as
                // a source-orthography debug rendering.
                const wHtml = finalParts.map(p =>
                    p.cls
                        ? `<tajweed class="${p.cls}">${p.text}</tajweed>`
                        : p.text
                ).join('');
                segments.push({
                    html: wHtml,
                    parts: finalParts.map(p => ({ text: p.text, cls: p.cls })),
                    rules: [...segRules],
                });
            }
            segParts = [];
            segRules = new Set();
        };

        for (const sub of subTokens) {
            if (sub.text) {
                segParts.push({ text: sub.text, cls: sub.cls });
                if (sub.cls) segRules.add(sub.cls);
            }
            if (sub.boundary) flush();
        }
        flush(); // final word

        return segments;
    }

    async function toggleTajweed() {
        const enabled = !isTajweedEnabled();
        document.body.dataset.tajweedEnabled = enabled ? 'true' : 'false';
        localStorage.setItem('quranApp_tajweedEnabled', enabled ? 'true' : 'false');
        updateTajweedButton();
        if (enabled) {
            const surah = elements.surahSelect.value;
            const ayah = elements.ayahSelect.value;
            if (surah && ayah) await fetchAndDisplayTajweed(surah, ayah);
        }
        refreshKhattRenderedWords();
    }

    async function fetchAndDisplayTajweed(surahNumber, ayahNumber) {
        try {
            await getTajweedHtml(surahNumber, ayahNumber);
            if (isTajweedEnabled()) {
                refreshKhattRenderedWords();
            }
            return;
        } catch (e) {
            console.error('Error loading tajweed:', e);
        }
    }

    /**
     * Reclassify madda_obligatory → madda_munfasil in the raw HTML string for display.
     * The heuristic mirrors flush() in parseTajweedIntoWords: if the tagged text has no
     * Arabic hamza character and there is no hamza in the remaining text up to the next
     * space, it's منفصل.
     */
    function _reclassifyMunfasilInHtml(html) {
        const _hamzaRe = /[\u0621\u0623\u0624\u0625\u0626]/;
        // Split on word boundaries (spaces between Arabic words)
        // We process the entire string token by token looking for madda_obligatory tags
        return html.replace(
            /(<tajweed\s+class=["']?madda_obligatory["']?>)([\s\S]*?)(<\/tajweed>)([\s\S]*?)(?= |$)/g,
            (match, open, inner, close, afterInSameWord) => {
                if (!_hamzaRe.test(inner) && !_hamzaRe.test(afterInSameWord)) {
                    return `<tajweed class="madda_munfasil">${inner}</tajweed>${afterInSameWord}`;
                }
                return match;
            }
        );
    }

    async function maybeRefreshTajweed(surahNumber, ayahNumber) {
        if (isTajweedEnabled()) {
            await fetchAndDisplayTajweed(surahNumber, ayahNumber);
        }
    }

    function updateTajweedButton() {
        const btn = document.getElementById('show-tajweed');
        if (!btn) return;
        const enabled = isTajweedEnabled();
        btn.classList.toggle('active', enabled);
        btn.setAttribute('aria-pressed', enabled ? 'true' : 'false');
        btn.innerHTML = '<i class="fas fa-palette"></i> التجويد';
    }

    // ── Nuzool ──────────────────────────────────────────────────────────────────────────
    function toggleNuzool() {
        const container = document.getElementById('nuzool-container');
        if (!container) return;
        const isHidden = container.style.display === 'none';
        container.style.display = isHidden ? 'block' : 'none';
        const btn = document.getElementById('show-nuzool');
        if (btn) btn.textContent = isHidden ? 'إخفاء نزول الآية' : 'نزول الآية';
    }

    function toggleWordMeaning() {
        elements.wordMeaningVisible = !elements.wordMeaningVisible;
        if (elements.wordMeaningVisible) {
            elements.wordMeaningContainer.style.display = 'block';
            // Refresh word meanings for the current verse when toggling to visible
            if (currentAyahData) {
                const verseKey = `${elements.surahSelect.value}:${elements.ayahSelect.value}`;
                const ayahText = getDisplayedAyahText(quranTextData?.[verseKey] || {}, currentAyahData.text || currentAyahData.raw_text || '');
                displayWordMeanings(currentAyahData.word_meanings_ordered || currentAyahData.word_meanings || {}, ayahText);
            }
        } else {
            elements.wordMeaningContainer.style.display = 'none';
        }
        updateWordMeaningButton();
    }

    function updateTransliterationButton() {
        const transliterationButton = document.getElementById('show-transliteration');
        const transliterationContainer = document.getElementById('transliteration-container');
        if (transliterationContainer.style.display === 'none') {
            transliterationButton.textContent = 'عرض النطق الحرفي ';
        } else {
            transliterationButton.textContent = 'اخفاء النطق الحرفي';
        }
    }

    function updateTafseerButton() {
        const tafseerButton = document.getElementById('show-tafseer');
        const tafseerContainer = document.getElementById('tafseer-container');
        if (tafseerContainer.style.display === 'none') {
            tafseerButton.textContent = 'عرض التفسير';
        } else {
            tafseerButton.textContent = 'اخفاء التفسير';
        }
    }

    function updateWordMeaningButton() {
        if (elements.wordMeaningVisible) {
            elements.toggleWordMeaningButton.textContent = 'اخفاء غريب الكلمات';
        } else {
            elements.toggleWordMeaningButton.textContent = 'عرض غريب الكلمات';
        }
    }

    // ── Recitation Guide ────────────────────────────────────────────────────

    async function toggleRecitationGuide() {
        const guideContainer = document.getElementById('recitation-guide-container');
        const guideBtn = document.getElementById('show-recitation-guide');
        if (!guideContainer) return;

        const isHidden = guideContainer.style.display === 'none';
        guideContainer.style.display = isHidden ? 'block' : 'none';

        if (guideBtn) {
            guideBtn.classList.toggle('active', isHidden);
            const btnText = guideBtn.querySelector('span');
            if (btnText) btnText.textContent = isHidden ? 'إخفاء دليل التلاوة' : 'دليل التلاوة';
        }

        if (isHidden) {
            await fetchAndBuildRecitationGuide();
            guideContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } else {
            detachGuideHighlightHandler();
        }
    }

    async function fetchAndBuildRecitationGuide() {
        const surah = elements.surahSelect.value;
        const ayah = elements.ayahSelect.value;
        if (!surah || !ayah) return;

        const guideContainer = document.getElementById('recitation-guide-container');
        guideContainer.innerHTML = '<div class="guide-loading"><i class="fas fa-spinner fa-spin"></i> جاري تحميل بيانات الوقف…</div>';

        try {
            const reciter = elements.reciterSelect.value;
            const qs = reciter ? `?reciter=${encodeURIComponent(reciter)}` : '';

            const [data, matchData, compareData] = await Promise.all([
                fetchData(`/api/recitation-guide/${surah}/${ayah}${qs}`),
                fetchData(`/api/pause-match/${surah}/${ayah}${qs}`).catch(() => null),
                fetchData(`/api/reciter-compare/${surah}/${ayah}${qs}`).catch(() => null),
            ]);
            const reciterName = RECITER_ARABIC_NAMES[reciter] || reciter;

            if (data.has_positions_db === false) {
                guideContainer.innerHTML =
                    `<div class="guide-no-waqf">` +
                    `<span class="guide-no-waqf-sym">🎙</span>` +
                    `<span class="guide-no-waqf-title">دليل التلاوة غير متاح لهذا القارئ</span>` +
                    `<span class="guide-no-waqf-body">لا توجد بيانات تسجيل لـ ${reciterName} بعد.</span>` +
                    `</div>`;
                return;
            }

            // Build word → time map from the reciter's word-alignment segments
            // so we can highlight the current guide segment as audio plays.
            const wordTimingMap = new Map();
            if (Array.isArray(currentSegments)) {
                currentSegments.forEach((seg) => {
                    const start = parseInt(seg.start_word_index, 10);
                    const end   = parseInt(seg.end_word_index,   10);
                    const sMs   = parseInt(seg.start_time, 10);
                    const eMs   = parseInt(seg.end_time,   10);
                    if (!isNaN(start) && !isNaN(end) && !isNaN(sMs) && !isNaN(eMs)) {
                        for (let i = start; i <= end; i++) {
                            if (!wordTimingMap.has(i)) {
                                wordTimingMap.set(i, { startMs: sMs, endMs: eMs });
                            }
                        }
                    }
                });
            }

            // Solo waqfs: stops this reciter makes that no other reciter shares.
            const uniquePauses = (compareData && compareData.has_data)
                ? (compareData.unique_pauses || [])
                : [];
            buildRecitationGuideFromSegments(guideContainer, data.segments || [], reciterName, wordTimingMap, uniquePauses);
            if (matchData && matchData.has_data) {
                buildPauseMatchPanel(guideContainer, matchData, reciterName);
            }
            if (compareData && compareData.has_data) {
                buildReciterComparePanel(guideContainer, compareData, reciterName);
            }
        } catch (error) {
            guideContainer.innerHTML = '<div class="guide-error"><i class="fas fa-triangle-exclamation"></i> خطأ في تحميل دليل التلاوة</div>';
            console.error('Recitation guide error:', error);
        }
    }

    function buildPauseMatchPanel(container, matchData, reciterName) {
        const { matches, pause_count } = matchData;
        // Sort: primary by combined score, secondary by precision
        const versions = Object.keys(matches).sort((a, b) => {
            const scoreA = matches[a].coverage_score ?? matches[a].score;
            const scoreB = matches[b].coverage_score ?? matches[b].score;
            if (scoreA !== scoreB) return scoreB - scoreA;
            return matches[b].score - matches[a].score;
        });
        if (!versions.length) return;
        // Nothing to report: the reciter made no discretionary (mid-verse) stops
        // and no mushaf marks this verse against. (The verse-end stop is excluded.)
        const anyMarks = versions.some(v => matches[v].mushaf_marks > 0);
        if (pause_count === 0 && !anyMarks) return;

        // Helpers ─────────────────────────────────────────────────────────────
        function toArabicNumerals(n) {
            return String(n).replace(/\d/g, d => '٠١٢٣٤٥٦٧٨٩'[d]);
        }

        // Build a natural-language verdict sentence for one mushaf entry
        function buildVerdict(ver, matched, total, score, mushaf_marks, marks_covered, coverage_score) {
            const recShort = reciterName;
            const allPrec = matched === total;
            const allCov  = mushaf_marks === 0 || marks_covered === mushaf_marks;
            const noPrec  = matched === 0;
            const noCov   = mushaf_marks > 0 && marks_covered === 0;
            const m = toArabicNumerals(matched);
            const t = toArabicNumerals(total);
            const c = toArabicNumerals(marks_covered);
            const mk = toArabicNumerals(mushaf_marks);

            let parts = [];

            if (total === 0) {
                // Only the (excluded) verse-end stop — no optional waqf to judge.
                parts.push(`لم يقف الشيخ وقوفاً اختيارية داخل الآية`);
            } else if (allPrec) {
                parts.push(`وافق الشيخ في جميع وقفاته (${m}/${t})`);
            } else if (noPrec) {
                parts.push(`لم توافق أيٌّ من وقفاته علامات هذا المصحف`);
            } else {
                parts.push(`وافق الشيخ في ${m} من أصل ${t} وقفة`);
            }

            if (mushaf_marks > 0) {
                if (allCov) {
                    parts.push(`وغطّى جميع علامات الوقف فيه (${c}/${mk})`);
                } else if (noCov) {
                    parts.push(`دون أن يمرّ على أيٍّ من علاماته (${mk} علامة)`);
                } else {
                    parts.push(`وغطّى ${c} من ${mk} علامة في المصحف`);
                }
            } else {
                parts.push(`(لا علامات وقف مخصّصة في هذا المصحف لهذه الآية)`);
            }

            return parts.join('، ');
        }

        function badgeLevel(score, coverage_score, mushaf_marks) {
            const eff = mushaf_marks > 0 ? Math.min(score, coverage_score) : score;
            if (eff === 100) return 'full';
            if (eff === 0) return 'none';
            return 'partial';
        }

        const BADGE = {
            full:    { label: 'مطابق تماماً', cls: 'pm-badge-full' },
            partial: { label: 'مطابق جزئياً', cls: 'pm-badge-partial' },
            none:    { label: 'غير مطابق', cls: 'pm-badge-none' },
        };

        const panel = document.createElement('div');
        panel.className = 'pause-match-panel';

        const title = document.createElement('div');
        title.className = 'pause-match-title';
        title.innerHTML = `<i class="fas fa-book-open"></i> تطابق وقوف ${reciterName} مع المصاحف`;
        panel.appendChild(title);

        const subtitle = document.createElement('p');
        subtitle.className = 'pause-match-subtitle';
        subtitle.textContent = `${toArabicNumerals(pause_count)} وقفة في هذه الآية — مرتّبة من الأعلى تطابقاً`;
        panel.appendChild(subtitle);

        const rows = document.createElement('div');
        rows.className = 'pause-match-rows';

        versions.forEach((ver, idx) => {
            const { matched, total, score, mushaf_marks, marks_covered, coverage_score } = matches[ver];
            const colorCls = getMushafColorClass(ver);
            const badge = BADGE[badgeLevel(score, coverage_score, mushaf_marks)];

            const card = document.createElement('div');
            card.className = `pause-match-card ${colorCls}`;

            const header = document.createElement('div');
            header.className = 'pause-match-card-header';

            const musName = document.createElement('span');
            musName.className = `pause-match-mushaf-name ${colorCls}`;
            musName.textContent = ver;
            header.appendChild(musName);

            const badgeEl = document.createElement('span');
            badgeEl.className = `pm-badge ${badge.cls}`;
            badgeEl.textContent = badge.label;
            header.appendChild(badgeEl);
            card.appendChild(header);

            const verdict = document.createElement('p');
            verdict.className = 'pause-match-verdict';
            verdict.textContent = buildVerdict(ver, matched, total, score, mushaf_marks, marks_covered, coverage_score);
            card.appendChild(verdict);

            // Precision bar only makes sense when there are discretionary stops.
            if (total > 0) {
                const precSection = document.createElement('div');
                precSection.className = 'pause-match-bar-section';

                const precHeader = document.createElement('div');
                precHeader.className = 'pause-match-bar-header';
                const precTitle = document.createElement('span');
                precTitle.className = 'pause-match-bar-title';
                precTitle.textContent = 'صحة وقفاته';
                const precHint = document.createElement('span');
                precHint.className = 'pause-match-bar-hint';
                precHint.textContent = 'كم وقفة منه لها سند في هذا المصحف؟';
                precHeader.appendChild(precTitle);
                precHeader.appendChild(precHint);
                precSection.appendChild(precHeader);

                const precRow = document.createElement('div');
                precRow.className = 'pause-match-metric-row';
                const precWrap = document.createElement('div');
                precWrap.className = 'pause-match-bar-wrap';
                const precBar = document.createElement('div');
                precBar.className = `pause-match-bar ${colorCls}`;
                precBar.style.width = '0%';
                setTimeout(() => { precBar.style.width = score + '%'; }, 50 + idx * 20);
                precWrap.appendChild(precBar);
                precRow.appendChild(precWrap);
                const precPct = document.createElement('span');
                precPct.className = 'pause-match-pct';
                precPct.textContent = `${toArabicNumerals(score)}٪ (${toArabicNumerals(matched)}/${toArabicNumerals(total)})`;
                precRow.appendChild(precPct);
                precSection.appendChild(precRow);
                card.appendChild(precSection);
            }

            if (mushaf_marks > 0) {
                const covSection = document.createElement('div');
                covSection.className = 'pause-match-bar-section';

                const covHeader = document.createElement('div');
                covHeader.className = 'pause-match-bar-header';
                const covTitle = document.createElement('span');
                covTitle.className = 'pause-match-bar-title';
                covTitle.textContent = 'تغطية علاماته';
                const covHint = document.createElement('span');
                covHint.className = 'pause-match-bar-hint';
                covHint.textContent = 'كم علامة وقف في المصحف وقف عندها الشيخ؟';
                covHeader.appendChild(covTitle);
                covHeader.appendChild(covHint);
                covSection.appendChild(covHeader);

                const covRow = document.createElement('div');
                covRow.className = 'pause-match-metric-row';
                const covWrap = document.createElement('div');
                covWrap.className = 'pause-match-bar-wrap';
                const covBar = document.createElement('div');
                covBar.className = `pause-match-coverage-bar ${colorCls}`;
                covBar.style.width = '0%';
                setTimeout(() => { covBar.style.width = coverage_score + '%'; }, 90 + idx * 20);
                covWrap.appendChild(covBar);
                covRow.appendChild(covWrap);
                const covPct = document.createElement('span');
                covPct.className = 'pause-match-pct';
                covPct.textContent = `${toArabicNumerals(coverage_score)}٪ (${toArabicNumerals(marks_covered)}/${toArabicNumerals(mushaf_marks)})`;
                covRow.appendChild(covPct);
                covSection.appendChild(covRow);
                card.appendChild(covSection);
            }

            rows.appendChild(card);
        });

        panel.appendChild(rows);
        container.appendChild(panel);
    }

    // ── Reciter-vs-reciter comparison panel ─────────────────────────────────
    function buildReciterComparePanel(container, compareData, subjectName) {
        const { comparisons, subject_mid_count } = compareData;
        const others = Object.keys(comparisons).sort(
            (a, b) => comparisons[b].similarity - comparisons[a].similarity
        );
        if (!others.length) return;

        function toAr(n) { return String(n).replace(/\d/g, d => '٠١٢٣٤٥٦٧٨٩'[d]); }

        const panel = document.createElement('div');
        panel.className = 'reciter-compare-panel';

        const title = document.createElement('div');
        title.className = 'pause-match-title';
        title.innerHTML = `<i class="fas fa-users"></i> مقارنة وقوف ${subjectName} مع القراء`;
        panel.appendChild(title);

        const subtitle = document.createElement('p');
        subtitle.className = 'pause-match-subtitle';
        subtitle.textContent = `${toAr(subject_mid_count)} وقفة وسط الآية (رأس الآية مستثنى) — مرتّبة بحسب التشابه`;
        panel.appendChild(subtitle);

        const rows = document.createElement('div');
        rows.className = 'pause-match-rows';

        others.forEach((other, idx) => {
            const { a_to_b_score, a_to_b_matched, a_to_b_total,
                    b_to_a_score, b_to_a_matched, b_to_a_total, similarity, comparable } = comparisons[other];
            const otherName = RECITER_ARABIC_NAMES[other] || other;

            const noMidPauses = a_to_b_total === 0 && b_to_a_total === 0;
            // Exactly one reciter pauses mid-verse — a symmetric % is meaningless,
            // so don't show "لا توافق" (which contradicts the verdict sentence).
            const oneSided = !noMidPauses && comparable === false;
            const badgeCls = (noMidPauses || oneSided) ? 'pm-badge-partial'
                           : similarity === 100  ? 'pm-badge-full'
                           : similarity === 0    ? 'pm-badge-none'
                                                 : 'pm-badge-partial';
            const badgeTxt = noMidPauses         ? 'لا وقوف وسطية'
                           : oneSided            ? 'لا يمكن التقييم'
                           : similarity === 100  ? 'توافق تام'
                           : similarity === 0    ? 'لا توافق'
                                                 : `توافق ${toAr(similarity)}٪`;

            const card = document.createElement('div');
            card.className = 'reciter-compare-card';

            // Header: other reciter name + similarity badge
            const header = document.createElement('div');
            header.className = 'pause-match-card-header';
            const nameEl = document.createElement('span');
            nameEl.className = 'reciter-compare-name';
            nameEl.textContent = otherName;
            header.appendChild(nameEl);
            const badgeEl = document.createElement('span');
            badgeEl.className = `pm-badge ${badgeCls}`;
            badgeEl.textContent = badgeTxt;
            header.appendChild(badgeEl);
            card.appendChild(header);

            // Verdict sentence
            const verdict = document.createElement('p');
            verdict.className = 'pause-match-verdict';
            let sentence = '';
            if (a_to_b_total === 0 && b_to_a_total === 0) {
                sentence = 'لا توجد وقفات وسط الآية لدى أيٍّ منهما للمقارنة.';
            } else if (a_to_b_total === 0) {
                sentence = `${subjectName} لا يقف وسط الآية — لا يمكن تقييم التوافق.`;
            } else if (b_to_a_total === 0) {
                sentence = `${otherName} لا يقف وسط الآية — لا يمكن تقييم التوافق.`;
            } else {
                const matchAB = a_to_b_matched === a_to_b_total ? 'جميع' : toAr(a_to_b_matched) + ' من ' + toAr(a_to_b_total);
                const matchBA = b_to_a_matched === b_to_a_total ? 'جميع' : toAr(b_to_a_matched) + ' من ' + toAr(b_to_a_total);
                sentence = `وقف ${subjectName} عند ${matchAB} وقفات ${otherName} — ووقف ${otherName} عند ${matchBA} وقفات ${subjectName}`;
            }
            verdict.textContent = sentence;
            card.appendChild(verdict);

            // Bar 1: A→B (subject's stops found in other)
            if (a_to_b_total > 0) {
                const sec1 = document.createElement('div');
                sec1.className = 'pause-match-bar-section';
                const h1 = document.createElement('div');
                h1.className = 'pause-match-bar-header';
                const t1 = document.createElement('span');
                t1.className = 'pause-match-bar-title';
                t1.textContent = `وقفات ${subjectName}`;
                const q1 = document.createElement('span');
                q1.className = 'pause-match-bar-hint';
                q1.textContent = `كم منها وقف عندها ${otherName} أيضاً؟`;
                h1.appendChild(t1); h1.appendChild(q1); sec1.appendChild(h1);
                const r1 = document.createElement('div');
                r1.className = 'pause-match-metric-row';
                const w1 = document.createElement('div');
                w1.className = 'pause-match-bar-wrap';
                const b1 = document.createElement('div');
                b1.className = 'reciter-compare-bar-a';
                b1.style.width = '0%';
                setTimeout(() => { b1.style.width = a_to_b_score + '%'; }, 50 + idx * 20);
                w1.appendChild(b1); r1.appendChild(w1);
                const p1 = document.createElement('span');
                p1.className = 'pause-match-pct';
                p1.textContent = `${toAr(a_to_b_score)}٪ (${toAr(a_to_b_matched)}/${toAr(a_to_b_total)})`;
                r1.appendChild(p1); sec1.appendChild(r1); card.appendChild(sec1);
            }

            // Bar 2: B→A (other's stops found in subject)
            if (b_to_a_total > 0) {
                const sec2 = document.createElement('div');
                sec2.className = 'pause-match-bar-section';
                const h2 = document.createElement('div');
                h2.className = 'pause-match-bar-header';
                const t2 = document.createElement('span');
                t2.className = 'pause-match-bar-title';
                t2.textContent = `وقفات ${otherName}`;
                const q2 = document.createElement('span');
                q2.className = 'pause-match-bar-hint';
                q2.textContent = `كم منها وقف عندها ${subjectName} أيضاً؟`;
                h2.appendChild(t2); h2.appendChild(q2); sec2.appendChild(h2);
                const r2 = document.createElement('div');
                r2.className = 'pause-match-metric-row';
                const w2 = document.createElement('div');
                w2.className = 'pause-match-bar-wrap';
                const b2 = document.createElement('div');
                b2.className = 'reciter-compare-bar-b';
                b2.style.width = '0%';
                setTimeout(() => { b2.style.width = b_to_a_score + '%'; }, 90 + idx * 20);
                w2.appendChild(b2); r2.appendChild(w2);
                const p2 = document.createElement('span');
                p2.className = 'pause-match-pct';
                p2.textContent = `${toAr(b_to_a_score)}٪ (${toAr(b_to_a_matched)}/${toAr(b_to_a_total)})`;
                r2.appendChild(p2); sec2.appendChild(r2); card.appendChild(sec2);
            }

            // Collapsible diff section — only when not 100% match
            const diff = comparisons[other].diff;
            if (similarity < 100 && diff && (diff.only_in_a.length || diff.only_in_b.length)) {
                const diffWrap = document.createElement('div');
                diffWrap.className = 'rc-diff-wrap';

                const toggle = document.createElement('button');
                toggle.className = 'rc-diff-toggle';
                toggle.innerHTML = '<i class="fas fa-chevron-down rc-diff-chevron"></i> عرض الفارق';
                diffWrap.appendChild(toggle);

                const body = document.createElement('div');
                body.className = 'rc-diff-body rc-diff-body-hidden';

                function makeDiffGroup(label, items, isA) {
                    if (!items.length) return;
                    const g = document.createElement('div');
                    g.className = 'rc-diff-group';
                    const lbl = document.createElement('span');
                    lbl.className = 'rc-diff-label';
                    lbl.textContent = label;
                    g.appendChild(lbl);
                    const chips = document.createElement('span');
                    chips.className = 'rc-diff-chips';
                    items.forEach(item => {
                        const chip = document.createElement('span');
                        chip.className = isA ? 'rc-diff-chip rc-diff-chip-a' : 'rc-diff-chip rc-diff-chip-b';
                        // Show segment text (uthmani_text from positions.db) — last 4 words
                        // are shown so the pause-point (end) is visible; full text on hover
                        const segWords = (item.text || '').split(' ').filter(Boolean);
                        const truncated = segWords.length > 4
                            ? '\u2026 ' + segWords.slice(-4).join(' ')
                            : (segWords.join(' ') || `ك${toAr(item.word_index + 1)}`);
                        chip.textContent = truncated;
                        chip.title = item.text || `الكلمة ${toAr(item.word_index + 1)}`;
                        chips.appendChild(chip);
                    });
                    g.appendChild(chips);
                    body.appendChild(g);
                }

                if (diff.only_in_a.length) {
                    makeDiffGroup(`وقف عندها ${subjectName} فقط`, diff.only_in_a, true);
                }
                if (diff.only_in_b.length) {
                    makeDiffGroup(`وقف عندها ${otherName} فقط`, diff.only_in_b, false);
                }

                toggle.addEventListener('click', () => {
                    const open = body.classList.toggle('rc-diff-body-hidden');
                    toggle.classList.toggle('rc-diff-toggle-open', !open);
                    toggle.querySelector('.rc-diff-chevron').style.transform = open ? '' : 'rotate(180deg)';
                });

                diffWrap.appendChild(body);
                card.appendChild(diffWrap);
            }

            rows.appendChild(card);
        });

        panel.appendChild(rows);
        container.appendChild(panel);
    }

    // ── positions.db-powered guide ───────────────────────────────────────────
    function buildRecitationGuideFromSegments(container, segments, reciterName, wordTimingMap = new Map(), uniquePauses = []) {
        container.innerHTML = '';
        detachGuideHighlightHandler();
        const uniquePauseSet = new Set((uniquePauses || []).map(Number));

        function toArabicNumerals(n) {
            return String(n).replace(/\d/g, d => '٠١٢٣٤٥٦٧٨٩'[d]);
        }

        if (!segments || segments.length === 0) {
            const noEl = document.createElement('div');
            noEl.className = 'guide-no-waqf';
            noEl.innerHTML =
                `<span class="guide-no-waqf-sym">۝</span>` +
                `<span class="guide-no-waqf-title">لا توجد علامات وقف لهذه الآية</span>` +
                `<span class="guide-no-waqf-body">اقرأ الآية كاملةً دون وقف، ثم قف عند رأس الآية</span>`;
            container.appendChild(noEl);
            return;
        }

        const wrapper = document.createElement('div');
        wrapper.className = 'recitation-guide';

        // Title — shows the reciter name, not mushaf version
        const titleEl = document.createElement('div');
        titleEl.className = 'guide-title';
        titleEl.innerHTML = `<i class="fas fa-route"></i> دليل التلاوة — ${reciterName || 'القارئ'}`;
        wrapper.appendChild(titleEl);

        const subtitleEl = document.createElement('p');
        subtitleEl.className = 'guide-subtitle';
        subtitleEl.textContent = 'الآية مقسّمة إلى مقاطع وفق مواضع الوقف. اقرأ كل مقطع حتى الرمز ثم قف أو استمر حسب الحكم.';
        wrapper.appendChild(subtitleEl);

        const segRow = document.createElement('div');
        segRow.className = 'guide-seg-row';
        segRow.dir = 'rtl';

        const builtSegEls = [];

        // Track the furthest word reached so we can detect a "back-up": a segment
        // that re-reads words already recited (the reciter stopped at a waqf then
        // resumed FROM that point rather than continuing past it — e.g. Suwaid at
        // 12:27 repeats from فكذبت). The waqf itself still counts; this only flags
        // the repetition so the reader sees it.
        let guideHighWater = 0;

        segments.forEach((seg, idx) => {
            const isLast = idx === segments.length - 1;
            const segEl = document.createElement('div');
            segEl.className = 'guide-segment';
            if (isLast) segEl.classList.add('guide-segment-last');

            const segStartW = parseInt(seg.start_word, 10);
            const segEndW   = parseInt(seg.end_word, 10);
            const repeatedCount = Number.isFinite(segStartW)
                ? Math.max(0, guideHighWater - segStartW)
                : 0;
            const isBackUp = repeatedCount > 0;
            if (Number.isFinite(segEndW)) guideHighWater = Math.max(guideHighWater, segEndW);
            if (isBackUp) segEl.classList.add('guide-segment-repeat');

            // Compute time range for this segment from word alignment timing.
            // positions.db start_word / end_word are 0-based; end_word is exclusive.
            if (wordTimingMap.size > 0 && seg.start_word != null && seg.end_word != null) {
                let segStartMs = Infinity, segEndMs = -Infinity;
                const wStart = parseInt(seg.start_word, 10);                 // 0-based, inclusive
                const wEnd   = Math.max(0, parseInt(seg.end_word, 10) - 1);  // exclusive → inclusive
                for (let wi = wStart; wi <= wEnd; wi++) {
                    const t = wordTimingMap.get(wi);
                    if (t) {
                        segStartMs = Math.min(segStartMs, t.startMs);
                        segEndMs   = Math.max(segEndMs,   t.endMs);
                    }
                }
                if (segStartMs !== Infinity) {
                    segEl.dataset.startMs = segStartMs;
                    segEl.dataset.endMs   = segEndMs;
                    segEl.classList.add('guide-segment-seekable');
                    segEl.title = 'انقر للانتقال إلى هذا المقطع';
                    segEl.addEventListener('click', () => {
                        elements.audioElement.currentTime = segStartMs / 1000;
                        if (elements.audioElement.paused) elements.audioElement.play().catch(() => {});
                    });
                }
            }

            // Segment number
            const segNum = document.createElement('span');
            segNum.className = 'guide-seg-num';
            segNum.textContent = toArabicNumerals(idx + 1);
            segEl.appendChild(segNum);

            // Strip any embedded waqf glyphs from the positions.db segment text.
            const segWords = (seg.text || '').split(' ')
                .filter(w => w.trim())
                .map(w => stripEmbeddedWaqf(w));

            // Repetition badge — the reciter resumed by re-reading earlier words.
            if (isBackUp) {
                const repBadge = document.createElement('span');
                repBadge.className = 'guide-seg-repeat-badge';
                repBadge.innerHTML = '<i class="fas fa-rotate-left"></i> تكرار';
                const fromWord = segWords.slice(0, repeatedCount).join(' ').trim();
                repBadge.title = fromWord
                    ? `أعاد القارئ القراءة من «${fromWord}»`
                    : 'أعاد القارئ القراءة من هذا الموضع';
                segEl.appendChild(repBadge);
            } else if (!isLast && Number.isFinite(segEndW) && uniquePauseSet.has(segEndW)) {
                // Solo waqf — a clean stop-and-continue no other reciter makes.
                const soloBadge = document.createElement('span');
                soloBadge.className = 'guide-seg-solo-badge';
                soloBadge.innerHTML = '<i class="fas fa-star"></i> انفرد بالوقف';
                soloBadge.title = 'انفرد القارئ بهذا الوقف بين القرّاء — لم يقف عنده غيره';
                segEl.appendChild(soloBadge);
            }

            // Verse words. The first `repeatedCount` words were already recited in
            // an earlier segment (re-read after backing up) — mark them so the
            // repetition is visible.
            const wordsEl = document.createElement('div');
            wordsEl.className = 'guide-seg-words';
            wordsEl.dir = 'rtl';
            segWords.forEach((w, wi) => {
                if (wi > 0) wordsEl.appendChild(document.createTextNode(' '));
                const wSpan = document.createElement('span');
                if (isBackUp && wi < repeatedCount) wSpan.className = 'guide-seg-repeated-word';
                wSpan.textContent = w;
                wordsEl.appendChild(wSpan);
            });
            segEl.appendChild(wordsEl);

            // Copy segment text button
            const copyBtn = document.createElement('button');
            copyBtn.type = 'button';
            copyBtn.className = 'guide-seg-copy-btn';
            copyBtn.title = 'نسخ نص المقطع';
            copyBtn.innerHTML = '<i class="fas fa-copy"></i>';
            const segText = segWords.join(' ');
            let copyResetTimer = null;
            copyBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                navigator.clipboard.writeText(segText).then(() => {
                    copyBtn.innerHTML = '<i class="fas fa-check"></i>';
                    clearTimeout(copyResetTimer);
                    copyResetTimer = setTimeout(() => { copyBtn.innerHTML = '<i class="fas fa-copy"></i>'; }, 1500);
                }).catch(() => {});
            });
            segEl.appendChild(copyBtn);

            // Waqf symbol + meaning. Last segment always gets رأس الآية marker.
            const waqfEntries = seg.waqf || [];
            if (waqfEntries.length > 0 || isLast) {
                const waqfEl = document.createElement('div');
                waqfEl.className = 'guide-seg-waqf';

                waqfEntries.forEach(entry => {
                    const raw = (entry.symbols || '').trim();
                    const normalized = normalizeNonWarshWaqfText(raw);
                    const info = getWaqfInfo(raw, entry.version || '');

                    const symSpan = document.createElement('span');
                    symSpan.className = 'guide-waqf-sym waqf-uthmanic';
                    symSpan.textContent = normalized || raw;
                    waqfEl.appendChild(symSpan);

                    const lblSpan = document.createElement('span');
                    lblSpan.className = 'guide-waqf-lbl';
                    lblSpan.textContent = info.meaning;
                    waqfEl.appendChild(lblSpan);
                });

                // رأس الآية — always valid to stop at the end of a verse
                if (isLast) {
                    const rasSymSpan = document.createElement('span');
                    rasSymSpan.className = 'guide-waqf-sym guide-waqf-ras-aya';
                    rasSymSpan.textContent = '\u06DD';
                    waqfEl.appendChild(rasSymSpan);

                    const rasLblSpan = document.createElement('span');
                    rasLblSpan.className = 'guide-waqf-lbl guide-waqf-ras-aya-lbl';
                    rasLblSpan.textContent = '\u0631\u0623\u0633 \u0627\u0644\u0622\u064a\u0629';
                    waqfEl.appendChild(rasLblSpan);
                }

                segEl.appendChild(waqfEl);

                // Arrow connector only between segments, not after the last
                if (!isLast) {
                    const arrow = document.createElement('div');
                    arrow.className = 'guide-seg-arrow';
                    arrow.innerHTML = '<i class="fas fa-arrow-left"></i>';
                    segEl.appendChild(arrow);
                }
            }

            segRow.appendChild(segEl);
            builtSegEls.push(segEl);
        });

        wrapper.appendChild(segRow);
        container.appendChild(wrapper);

        // Attach audio progress highlight if timing data is available.
        const hasTimingData = builtSegEls.some(el => el.dataset.startMs !== undefined);
        if (hasTimingData) {
            attachGuideHighlightHandler(builtSegEls);
        }
    }

    function attachGuideHighlightHandler(segmentEls) {
        detachGuideHighlightHandler();
        elements.audioElement._guideTimeUpdateHandler = () => {
            const ms = elements.audioElement.currentTime * 1000;
            segmentEls.forEach((el) => {
                const start = parseFloat(el.dataset.startMs);
                const end   = parseFloat(el.dataset.endMs);
                if (!isNaN(start) && !isNaN(end)) {
                    el.classList.toggle('guide-segment-active', ms >= start && ms <= end);
                }
            });
        };
        elements.audioElement.addEventListener('timeupdate', elements.audioElement._guideTimeUpdateHandler);
    }

    function detachGuideHighlightHandler() {
        if (elements.audioElement._guideTimeUpdateHandler) {
            elements.audioElement.removeEventListener('timeupdate', elements.audioElement._guideTimeUpdateHandler);
            elements.audioElement._guideTimeUpdateHandler = null;
        }
    }
    function buildRecitationGuideHTML(container, verseText, waqfData, versions) {
        container.innerHTML = '';
        const words = (verseText || '').split(' ').filter(w => w.trim());

        // No waqf data
        if (!waqfData || waqfData.length === 0) {
            const noWaqfEl = document.createElement('div');
            noWaqfEl.className = 'guide-no-waqf';
            noWaqfEl.innerHTML =
                `<span class="guide-no-waqf-sym">\u06DD</span>` +
                `<span class="guide-no-waqf-title">\u0644\u0627 \u062a\u0648\u062c\u062f \u0639\u0644\u0627\u0645\u0627\u062a \u0648\u0642\u0641 \u0644\u0647\u0630\u0647 \u0627\u0644\u0622\u064a\u0629</span>` +
                `<span class="guide-no-waqf-body">\u0627\u0642\u0631\u0623 \u0627\u0644\u0622\u064a\u0629 \u0643\u0627\u0645\u0644\u0629\u064b \u062f\u0648\u0646 \u0648\u0642\u0641\u060c \u062b\u0645 \u0642\u0641 \u0639\u0646\u062f \u0631\u0623\u0633 \u0627\u0644\u0622\u064a\u0629</span>`;
            container.appendChild(noWaqfEl);
            return;
        }

        // Build waqf map: tokenIndex -> [{symbols, version}]
        const waqfMap = buildWaqfByTokenIndex(waqfData, words);

        // Group words into reading segments
        const segments = [];
        let currentWords = [];

        for (let i = 0; i < words.length; i++) {
            const entries = waqfMap.get(i);
            currentWords.push(words[i]);
            if (entries && entries.length > 0) {
                segments.push({ words: [...currentWords], waqf: entries });
                currentWords = [];
            }
        }
        if (currentWords.length > 0) {
            segments.push({ words: currentWords, waqf: null });
        }

        const wrapper = document.createElement('div');
        wrapper.className = 'recitation-guide';

        const versionLabel = versions && versions.length ? versions.join(' + ') : '\u0627\u0644\u062d\u0635\u0631\u064a';
        const titleEl = document.createElement('div');
        titleEl.className = 'guide-title';
        titleEl.innerHTML = `<i class="fas fa-route"></i> \u062f\u0644\u064a\u0644 \u0627\u0644\u062a\u0644\u0627\u0648\u0629 \u2014 \u0648\u0642\u0641 ${versionLabel}`;
        wrapper.appendChild(titleEl);

        const subtitleEl = document.createElement('p');
        subtitleEl.className = 'guide-subtitle';
        subtitleEl.textContent = '\u0627\u0644\u0622\u064a\u0629 \u0645\u0642\u0633\u0651\u0645\u0629 \u0625\u0644\u0649 \u0645\u0642\u0627\u0637\u0639 \u0648\u0641\u0642 \u0645\u0648\u0627\u0636\u0639 \u0627\u0644\u0648\u0642\u0641. \u0627\u0642\u0631\u0623 \u0643\u0644 \u0645\u0642\u0637\u0639 \u062d\u062a\u0649 \u0627\u0644\u0631\u0645\u0632 \u062b\u0645 \u0642\u0641 \u0623\u0648 \u0627\u0633\u062a\u0645\u0631 \u062d\u0633\u0628 \u0627\u0644\u062d\u0643\u0645.';
        wrapper.appendChild(subtitleEl);

        const segRow = document.createElement('div');
        segRow.className = 'guide-seg-row';
        segRow.dir = 'rtl';

        segments.forEach((seg, idx) => {
            const segEl = document.createElement('div');
            segEl.className = 'guide-segment';
            if (!seg.waqf) segEl.classList.add('guide-segment-last');

            const segNum = document.createElement('span');
            segNum.className = 'guide-seg-num';
            segNum.textContent = String(idx + 1);
            segEl.appendChild(segNum);

            const wordsEl = document.createElement('div');
            wordsEl.className = 'guide-seg-words';
            wordsEl.dir = 'rtl';
            wordsEl.textContent = seg.words.map(w => stripEmbeddedWaqf(w)).join(' ');
            segEl.appendChild(wordsEl);

            if (seg.waqf) {
                const waqfEl = document.createElement('div');
                waqfEl.className = 'guide-seg-waqf';

                seg.waqf.forEach(entry => {
                    const raw = (entry.symbols || '').trim();
                    const normalized = normalizeNonWarshWaqfText(raw);
                    const isWarshEntry = isWarshMushafVersion(entry.version);
                    const info = getWaqfInfo(raw, entry.version || '');
                    const mushafCls = getMushafColorClass(entry.version);
                    const fontCls = isWarshEntry ? ' waqf-warsh' : ' waqf-uthmanic';

                    const symSpan = document.createElement('span');
                    symSpan.className = 'guide-waqf-sym ' + mushafCls + fontCls;
                    symSpan.textContent = normalized || raw;
                    waqfEl.appendChild(symSpan);

                    if (entry.version) {
                        const badge = document.createElement('span');
                        badge.className = 'guide-mushaf-badge ' + mushafCls;
                        badge.textContent = entry.version;
                        waqfEl.appendChild(badge);
                    }

                    const lblSpan = document.createElement('span');
                    lblSpan.className = 'guide-waqf-lbl';
                    lblSpan.textContent = info.meaning;
                    waqfEl.appendChild(lblSpan);
                });

                segEl.appendChild(waqfEl);

                const arrow = document.createElement('div');
                arrow.className = 'guide-seg-arrow';
                arrow.innerHTML = '<i class="fas fa-arrow-left"></i>';
                segEl.appendChild(arrow);
            }

            segRow.appendChild(segEl);
        });

        wrapper.appendChild(segRow);

        const seenVersions = [...new Set(
            segments.flatMap(s => (s.waqf || []).map(e => e.version)).filter(Boolean)
        )];
        if (seenVersions.length > 0) {
            const legendEl = document.createElement('div');
            legendEl.className = 'guide-legend';
            legendEl.innerHTML = '<span class="guide-legend-title">\u0627\u0644\u0623\u0644\u0648\u0627\u0646:</span>' +
                seenVersions.map(v => {
                    const cls = getMushafColorClass(v);
                    const isWarsh = isWarshMushafVersion(v);
                    return `<span class="guide-legend-item">` +
                        `<span class="guide-waqf-sym ${cls}${isWarsh ? ' waqf-warsh' : ' waqf-uthmanic'}" style="font-size:0.85rem">\u25cf</span> ${v}` +
                        `</span>`;
                }).join('');
            wrapper.appendChild(legendEl);
        }

        container.appendChild(wrapper);
    }

    function createWordElement(word, index, wordIndexToSegmentMap) {
        const wordElement = document.createElement('span');
        wordElement.className = 'word-token';
        const cleanText = stripEmbeddedWaqf(word);
        wordElement.dataset.textOriginal = word;
        wordElement.dataset.textClean = cleanText;
        const mode = getCurrentWaqfMode();
        const wordContent = document.createElement('span');
        wordContent.className = 'word-content';
        const wordBase = document.createElement('span');
        wordBase.className = 'word-base';
        const visibleText = (mode === 'selected' || mode === 'none') ? cleanText : word;
        wordBase.textContent = getDisplayedWordText(visibleText);
        wordContent.appendChild(wordBase);
        wordElement.appendChild(wordContent);
        wordElement.dataset.index = index;
        wordElement.addEventListener('click', () => {
            playWordSegment(index, wordIndexToSegmentMap);
        });
        wordElement.addEventListener('mouseenter', () => showWordMeaningTooltip(wordElement));
        wordElement.addEventListener('mouseleave', () => {
            document.querySelectorAll('.word-meaning-tooltip').forEach(t => t.remove());
        });
        return wordElement;
    }

    function findWordMeaning(wordText, wordMeanings) {
        if (!wordText || !wordMeanings) return null;
        const clean = wordText.replace(/[٠-٩0-9]/g, '').trim();
        if (wordMeanings[clean]) return wordMeanings[clean];
        if (wordMeanings[wordText]) return wordMeanings[wordText];
        for (const [key, meaning] of Object.entries(wordMeanings)) {
            if (key.includes(clean) || clean.includes(key)) return meaning;
        }
        return null;
    }

    function showWordMeaningTooltip(wordEl) {
        document.querySelectorAll('.word-meaning-tooltip').forEach(t => t.remove());
        if (!currentAyahData?.word_meanings) return;

        const wordText = wordEl.dataset.textClean || wordEl.textContent;
        const meaning = findWordMeaning(wordText, currentAyahData.word_meanings);
        if (!meaning) return;

        const tooltip = document.createElement('div');
        tooltip.className = 'word-meaning-tooltip';
        tooltip.textContent = meaning;
        document.body.appendChild(tooltip);

        const rect = wordEl.getBoundingClientRect();
        tooltip.style.top  = (rect.bottom + window.scrollY + 6) + 'px';
        tooltip.style.left = (rect.left  + window.scrollX) + 'px';
    }

    function mapSegmentsToWords(segments, wordIndexToSegmentMap) {
        if (!Array.isArray(segments) || !wordIndexToSegmentMap) {
            console.error('Invalid segments or wordIndexToSegmentMap');
            return;
        }
        
        segments.forEach(segment => {
            if (typeof segment === 'object' && segment !== null) {
                const { start_word_index, end_word_index, start_time, end_time } = segment;
                
                // Validate segment data
                if (start_word_index != null && end_word_index != null && start_time != null && end_time != null) {
                    for (let i = parseInt(start_word_index); i <= parseInt(end_word_index); i++) {
                        wordIndexToSegmentMap.set(i, { startTime: parseInt(start_time), endTime: parseInt(end_time) });
                    }
                } else {
                    console.warn('Incomplete segment data:', segment);
                }
            } else {
                console.error('Invalid segment format:', segment);
            }
        });
    }

    function highlightWords(wordElements, wordIndexToSegmentMap) {
        const currentTime = elements.audioElement.currentTime * 1000;
        
        // Use cached elements instead of DOM queries for better performance
        wordElements.forEach((wordElement, index) => {
            if (!wordElement) return;
            const segment = wordIndexToSegmentMap.get(index);
            if (segment && currentTime >= segment.startTime && currentTime <= segment.endTime) {
                if (!wordElement.classList.contains('highlight')) {
                    wordElement.classList.add('highlight');
                }
            } else {
                if (wordElement.classList.contains('highlight')) {
                    wordElement.classList.remove('highlight');
                }
            }
        });
    }

    function playWordSegment(index, wordIndexToSegmentMap) {
        const segment = wordIndexToSegmentMap.get(index);
        if (segment) {
            elements.audioElement.currentTime = segment.startTime / 1000;
            elements.audioElement.play();
            updatePlayPauseButton();
        }
    }

    async function loadNextAyah() {
        // Clean up range mode if active
        if (elements.playPauseButton.rangePlayPauseHandler) {
            cleanupRangeMode();
        }
        
        const currentAyahIndex = elements.ayahSelect.selectedIndex;
        if (currentAyahIndex < elements.ayahSelect.options.length - 1) {
            elements.ayahSelect.selectedIndex = currentAyahIndex + 1;
            currentRepeatCount = 0; // Reset repeat count on navigation
            await loadQuranData();
            elements.audioElement.play();
            updatePlayPauseButton();
        }
    }

    async function loadPrevAyah() {
        // Clean up range mode if active
        if (elements.playPauseButton.rangePlayPauseHandler) {
            cleanupRangeMode();
        }
        
        const currentAyahIndex = elements.ayahSelect.selectedIndex;
        if (currentAyahIndex > 0) {
            elements.ayahSelect.selectedIndex = currentAyahIndex - 1;
            currentRepeatCount = 0; // Reset repeat count on navigation
            await loadQuranData();
            elements.audioElement.play();
            updatePlayPauseButton();
        }
    }

    function handleRepeatChange() {
        const repeatValue = elements.repeatSelect.value;
        
        if (repeatValue === 'loop') {
            maxRepeats = Infinity;
        } else {
            maxRepeats = parseInt(repeatValue, 10);
        }
        
        // Reset current repeat count when user changes setting
        currentRepeatCount = 0;
        updatePlayPauseButton();
    }
    
    elements.repeatSelect.addEventListener('change', handleRepeatChange);
    
    elements.audioElement.addEventListener('ended', () => {
        // In range mode the range's own onEnded handler manages repeat + advancement
        if (isRangeMode) return;

        currentRepeatCount++;
        
        if (currentRepeatCount < maxRepeats) {
            elements.audioElement.currentTime = 0;
            elements.audioElement.play().then(updatePlayPauseButton).catch(() => {});
        } else {
            // Reset for next play
            currentRepeatCount = 0;
            updatePlayPauseButton();
        }
    });


    function toggleDarkMode() {
        if (document.body.classList.contains('sepia-mode')) {
            document.body.classList.remove('sepia-mode');
            elements.sepiaModeToggle.checked = false;
        }
        document.body.classList.toggle('dark-mode');
        localStorage.setItem('quranApp_theme', document.body.classList.contains('dark-mode') ? 'dark' : 'light');
    }

    function toggleSepiaMode() {
        if (document.body.classList.contains('dark-mode')) {
            document.body.classList.remove('dark-mode');
            elements.darkModeToggle.checked = false;
        }
        document.body.classList.toggle('sepia-mode');
        localStorage.setItem('quranApp_theme', document.body.classList.contains('sepia-mode') ? 'sepia' : 'light');
    }

    function toggleRangeSelection() {
        if (elements.rangeSelection) {
            elements.rangeSelection.style.display = elements.rangeSelection.style.display === 'none' ? 'block' : 'none';
        }
    }

    function showModal() {
        elements.modal.classList.add('show');
    }

    function closeModal() {
        elements.modal.classList.remove('show');
    }

    async function playRange() {
        const startAyahIndex = elements.startAyahSelect.selectedIndex;
        const endAyahIndex = elements.endAyahSelect.selectedIndex;
        if (startAyahIndex <= endAyahIndex) {
            isRangeMode = true;
            currentRepeatCount = 0;
            elements.ayahSelect.selectedIndex = startAyahIndex;
            await loadQuranData();
            elements.audioElement.play();
            updatePlayPauseButton();
            closeModal();

            // Remove existing range handlers to prevent memory leaks
            if (elements.audioElement.rangeEndedHandler) {
                elements.audioElement.removeEventListener('ended', elements.audioElement.rangeEndedHandler);
            }
            if (elements.playPauseButton.rangePlayPauseHandler) {
                elements.playPauseButton.removeEventListener('click', elements.playPauseButton.rangePlayPauseHandler);
            }

            // Remove the original play/pause event listener to prevent conflicts
            elements.playPauseButton.removeEventListener('click', togglePlayPause);

            const onEnded = async () => {
                if (elements.ayahSelect.selectedIndex < endAyahIndex) {
                    // More verses left in this loop — advance to next
                    elements.ayahSelect.selectedIndex++;
                    await loadQuranData();
                    elements.audioElement.play();
                    updatePlayPauseButton();
                } else {
                    // Reached end of range — check if we should loop the whole range again
                    currentRepeatCount++;
                    if (currentRepeatCount < maxRepeats) {
                        // Loop back to the start verse
                        elements.ayahSelect.selectedIndex = startAyahIndex;
                        await loadQuranData();
                        elements.audioElement.play();
                        updatePlayPauseButton();
                    } else {
                        // All loops done — clean up
                        cleanupRangeMode();
                        updatePlayPauseButton();
                    }
                }
            };

            const onPlayPause = () => {
                if (elements.audioElement.paused) {
                    elements.audioElement.play();
                } else {
                    elements.audioElement.pause();
                }
                updatePlayPauseButton();
            };

            // Store handlers for cleanup
            elements.audioElement.rangeEndedHandler = onEnded;
            elements.playPauseButton.rangePlayPauseHandler = onPlayPause;

            elements.audioElement.addEventListener('ended', onEnded);
            elements.playPauseButton.addEventListener('click', onPlayPause);
        }
    }

    function cleanupRangeMode() {
        isRangeMode = false;
        currentRepeatCount = 0;
        // Remove range-specific event handlers
        if (elements.audioElement.rangeEndedHandler) {
            elements.audioElement.removeEventListener('ended', elements.audioElement.rangeEndedHandler);
            elements.audioElement.rangeEndedHandler = null;
        }
        if (elements.playPauseButton.rangePlayPauseHandler) {
            elements.playPauseButton.removeEventListener('click', elements.playPauseButton.rangePlayPauseHandler);
            elements.playPauseButton.rangePlayPauseHandler = null;
        }
        // Restore the original play/pause event listener
        elements.playPauseButton.addEventListener('click', togglePlayPause);
    }

    function populateSelectOptions(data, selectElement, valueKey, textKey, prefix = '') {
        if (!data || !Array.isArray(data) || !selectElement) {
            console.error('Invalid data or select element for populateSelectOptions');
            return;
        }
        
        selectElement.innerHTML = '';
        data.forEach(item => {
            const option = document.createElement('option');
            option.value = valueKey ? item[valueKey] : item;
            option.textContent = `${prefix} ${textKey ? item[textKey] : item}`;
            selectElement.appendChild(option);
        });
    }

    function handleError(logMessage, error, container, userMessage) {
        console.error(logMessage, error);
        container.innerHTML = `<div class="error">${userMessage}</div>`;
    }

    async function fetchData(url) {
        try {
            const response = await fetch(url);
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            return response.json();
        } catch (error) {
            console.error(`Failed to fetch data from ${url}:`, error);
            throw error;
        }
    }

    function changeFont(font) {
        const quranText = document.getElementById('quran-text');
        quranText.className = ''; // Reset all font classes
        quranText.classList.add(font);
        // Track exact font name so CSS can apply per-font rules (e.g. #tajweed-text)
        document.body.dataset.quranFont = font;
        // Track font family so CSS can apply per-font rules to guide-seg-words, diff chips, etc.
        if (font === 'indopak_nastaleeq' || font === 'indopak_nastaleeq_2') {
            document.body.dataset.fontType = 'indopak';
        } else {
            // Store the exact font name so CSS selectors like body[data-font-type="digital_khatt"] work
            document.body.dataset.fontType = font;
        }
        // Show/hide the justification slider for Digital Khatt family fonts
        const isKhattFont = (font === 'digital_khatt' || font === 'old_madina');
        if (elements.khattJustifyRow) {
            elements.khattJustifyRow.style.display = isKhattFont ? '' : 'none';
        }
        if (!isKhattFont) {
            document.documentElement.style.removeProperty('--khatt-column-gap');
            document.documentElement.style.removeProperty('--khatt-row-gap');
            document.documentElement.style.removeProperty('--khatt-word-margin-x');
            refreshKhattRenderedWords();
        } else {
            const saved = parseInt(localStorage.getItem('quranApp_khattJustify') ?? '50', 10);
            applyKhattJustify(saved);
            if (elements.khattJustifySlider) elements.khattJustifySlider.value = saved;
            if (elements.khattJustifyValue) elements.khattJustifyValue.textContent = saved + '%';
        }
    }

    function applyKhattJustify(value) {
        pendingKhattJustifyValue = value;
        if (elements.khattJustifySlider) {
            elements.khattJustifySlider.value = String(value);
        }
        if (khattJustifyFrameId) {
            cancelAnimationFrame(khattJustifyFrameId);
        }
        khattJustifyFrameId = requestAnimationFrame(() => {
            khattJustifyFrameId = 0;
            if (pendingKhattJustifyValue == null) return;
            refreshKhattRenderedWords();
        });
    }

    function togglePlayPause() {
        if (!elements.audioElement) {
            console.error('Audio element not found');
            return;
        }
        
        if (elements.audioElement.paused) {
            // Reset repeat count when starting playback
            currentRepeatCount = 0;
            elements.audioElement.play().catch(error => {
                console.error('Error playing audio:', error);
            });
            elements.playPauseButton.classList.remove('fa-play');
            elements.playPauseButton.classList.add('fa-pause');
        } else {
            elements.audioElement.pause();
            elements.playPauseButton.classList.remove('fa-pause');
            elements.playPauseButton.classList.add('fa-play');
        }
    }

    function updatePlayPauseButton() {
        if (!elements.audioElement || !elements.playPauseButton) {
            console.error('Audio element or play pause button not found');
            return;
        }
        const btn = elements.playPauseButton;
        const icon = btn.querySelector('i');
        const label = btn.querySelector('span');
        if (elements.audioElement.paused) {
            btn.classList.remove('fa-pause');
            btn.classList.add('fa-play');
            if (icon)  { icon.classList.remove('fa-pause'); icon.classList.add('fa-play'); }
            if (label) label.textContent = 'تشغيل';
        } else {
            btn.classList.remove('fa-play');
            btn.classList.add('fa-pause');
            if (icon)  { icon.classList.remove('fa-play'); icon.classList.add('fa-pause'); }
            if (label) label.textContent = 'إيقاف';
        }
    }

    // Bookmark functions
    function getBookmarks() {
        const bookmarks = localStorage.getItem('quranApp_bookmarks');
        return bookmarks ? JSON.parse(bookmarks) : [];
    }
    
    function saveBookmarks(bookmarks) {
        localStorage.setItem('quranApp_bookmarks', JSON.stringify(bookmarks));
    }
    
    // Toast notification function
    function showToast(message, duration = 2000) {
        // Remove existing toast if any
        const existingToast = document.querySelector('.toast');
        if (existingToast) {
            existingToast.remove();
        }
        
        const toast = document.createElement('div');
        toast.className = 'toast';
        toast.textContent = message;
        document.body.appendChild(toast);
        
        setTimeout(() => {
            toast.remove();
        }, duration);
    }
    
    function addBookmark() {
        const surah = elements.surahSelect.value;
        const ayah = elements.ayahSelect.value;
        const surahName = elements.surahSelect.options[elements.surahSelect.selectedIndex]?.text || `سورة ${surah}`;
        
        if (!surah || !ayah) {
            showToast('الرجاء اختيار سورة وآية');
            return;
        }
        
        const bookmarks = getBookmarks();
        const bookmarkKey = `${surah}:${ayah}`;
        
        // Check if bookmark already exists
        if (bookmarks.some(b => b.key === bookmarkKey)) {
            showToast('هذه الآية محفوظة بالفعل');
            return;
        }
        
        bookmarks.push({
            key: bookmarkKey,
            surah: surah,
            ayah: ayah,
            surahName: surahName,
            timestamp: new Date().toISOString()
        });
        
        saveBookmarks(bookmarks);
        
        // Visual feedback
        elements.bookmarkButton.innerHTML = '<i class="fas fa-check"></i> <span>تم الحفظ</span>';
        setTimeout(() => {
            elements.bookmarkButton.innerHTML = '<i class="fas fa-bookmark"></i> <span>حفظ علامة</span>';
        }, 1500);
    }
    
    function removeBookmark(key) {
        let bookmarks = getBookmarks();
        bookmarks = bookmarks.filter(b => b.key !== key);
        saveBookmarks(bookmarks);
        renderBookmarks();
    }
    
    function goToBookmark(surah, ayah) {
        elements.surahSelect.value = surah;
        loadAyahs().then(() => {
            elements.ayahSelect.value = ayah;
            loadQuranData();
        });
        hideBookmarksModal();
    }
    
    // Sanitize text to prevent XSS
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    function renderBookmarks() {
        const bookmarks = getBookmarks();
        
        if (bookmarks.length === 0) {
            elements.bookmarksList.innerHTML = '<p style="text-align: center; color: #888;">لا توجد علامات مرجعية</p>';
            return;
        }
        
        // Clear existing content
        elements.bookmarksList.innerHTML = '';
        
        // Create bookmark items using DOM methods instead of innerHTML with user data
        bookmarks.forEach(bookmark => {
            const itemDiv = document.createElement('div');
            itemDiv.className = 'bookmark-item';
            itemDiv.style.cssText = 'display: flex; justify-content: space-between; align-items: center; padding: 10px; margin: 5px 0; background: var(--card-bg, #f8f9fa); border-radius: 8px; border: 1px solid var(--border-color, #e2e8f0);';
            
            const textSpan = document.createElement('span');
            textSpan.style.cssText = 'cursor: pointer; flex: 1;';
            textSpan.textContent = `${bookmark.surahName} - آية ${bookmark.ayah}`;
            textSpan.addEventListener('click', () => {
                goToBookmark(bookmark.surah, bookmark.ayah);
            });
            
            const deleteBtn = document.createElement('button');
            deleteBtn.style.cssText = 'background: #ef4444; color: white; border: none; border-radius: 4px; padding: 5px 10px; cursor: pointer; margin-right: 10px;';
            deleteBtn.innerHTML = '<i class="fas fa-trash"></i>';
            deleteBtn.addEventListener('click', () => {
                removeBookmark(bookmark.key);
            });
            
            itemDiv.appendChild(textSpan);
            itemDiv.appendChild(deleteBtn);
            elements.bookmarksList.appendChild(itemDiv);
        });
    }
    
    function showBookmarksModal() {
        renderBookmarks();
        elements.bookmarksModal.classList.add('show');
    }
    
    function hideBookmarksModal() {
        elements.bookmarksModal.classList.remove('show');
    }

    // Initialize word meanings visibility
    elements.wordMeaningVisible = false;
    elements.wordMeaningContainer.style.display = 'none';
    updateWordMeaningButton();

    loadAyahs();

    // Expose a hook so the memorization overlay can navigate the main page to a verse.
    // Called with (surah, ayah); updates selects + loads verse data without auto-playing.
    window.__memoNavigate = async function(surah, ayah) {
        try {
            if (String(elements.surahSelect.value) !== String(surah)) {
                elements.surahSelect.value = surah;
                const opts = await fetchData(`/api/surahs/${surah}/ayahs`).catch(() => null);
                if (opts) {
                    elements.ayahSelect.innerHTML = opts.map(a => `<option value="${a.ayah_number}">${a.ayah_number}</option>`).join('');
                }
            }
            elements.ayahSelect.value = ayah;
            await loadQuranData();
        } catch (e) {}
    };

    // Called by the memo IIFE to drive word-by-word highlighting on the main page
    // while memo-audio plays. wordTimes: [[wordIdx, startSec, endSec], ...] or null to clear.
    window.__memoHighlightWithTimes = function(wordTimes) {
        const memoAudio = document.getElementById('memo-audio');
        if (!memoAudio) return;
        if (memoAudio._memoHlHandler) {
            memoAudio.removeEventListener('timeupdate', memoAudio._memoHlHandler);
            memoAudio._memoHlHandler = null;
        }
        document.querySelectorAll('#quran-text .word-token.highlight').forEach(el => el.classList.remove('highlight'));
        if (!wordTimes || !wordTimes.length) return;
        const timeMap = new Map(wordTimes.map(([idx, s, e]) => [idx, { s, e }]));
        let lastHlTime = 0;
        memoAudio._memoHlHandler = () => {
            const now = Date.now();
            if (now - lastHlTime < 80) return;
            lastHlTime = now;
            const t = memoAudio.currentTime;
            document.querySelectorAll('#quran-text .word-token[data-index]').forEach(el => {
                const seg = timeMap.get(parseInt(el.dataset.index, 10));
                el.classList.toggle('highlight', !!(seg && t >= seg.s && t <= seg.e));
            });
        };
        memoAudio.addEventListener('timeupdate', memoAudio._memoHlHandler);
    };
});

// ══ Memorization mode — Circular Segmented Repetition ════════════════════════
// Self-contained: dedicated <audio>, per-surah Husary timeline, schedule of
// [start,end] ranges (verse / phrase / cumulative-link) played with precise
// stop-at-end. Does not touch the main per-ayah player.
(function initMemorizationMode() {
    if (window.__memoInit) return;
    window.__memoInit = true;

    function ready() {
        const modal = document.getElementById('memorizationModal');
        if (!modal) return;
        const $ = id => document.getElementById(id);
        const audio = $('memo-audio');
        const els = {
            open: $('show-memorization'),
            close: modal.querySelector('.memo-close'),
            startAyah: $('memo-start-ayah'),
            endAyah: $('memo-end-ayah'),
            verseReps: $('memo-verse-reps'),
            linkReps: $('memo-link-reps'),
            cumulative: $('memo-cumulative'),
            splitLong: $('memo-split-long'),


            hint: $('memo-hint'),
            startBtn: $('memo-start'),
            reciterSelect: $('memo-reciter-select'),
            verseList: $('memo-verse-list'),
            // overlay bar elements
            overlay: $('memo-overlay'),
            overlayVerse: $('memo-overlay-verse'),
            overlayStatus: $('memo-overlay-status'),
            overlayBar: $('memo-overlay-bar'),
            overlayPause: $('memo-overlay-pause'),
            overlayStop: $('memo-overlay-stop'),
        };

        let data = null;        // /api/memorization payload
        let schedule = [];      // [{start,end,ayah,label,rep,repTotal}]
        let stepIdx = -1;
        let monitorId = null;
        let loadedSurah = null;
        let loadedReciter = null;
        let pendingSeek = false;

        const LONG_SEC = 12;    // verses longer than this get phrase-split
        const EPS = 0.05;

        const getCurrentSurah = () => {
            const sel = document.getElementById('surah-select');
            return sel && sel.value ? parseInt(sel.value, 10) : 1;
        };
        const getCurrentFontType = () => document.body.dataset.fontType || 'qpc_hafs';
        const getCurrentReciter = () => els.reciterSelect ? els.reciterSelect.value : 'husary';

        let recitersFetched = false;
        async function loadReciters() {
            if (recitersFetched || !els.reciterSelect) return;
            try {
                const resp = await fetch('/api/memorization-reciters');
                if (!resp.ok) return;
                const list = await resp.json();
                if (!list.length) return;
                els.reciterSelect.innerHTML = list
                    .map(r => `<option value="${r.id}">${r.name_ar}</option>`)
                    .join('');
                recitersFetched = true;
            } catch (e) {}
        }
        // Strip the trailing verse-number ornament/digits (not recited)
        const stripNum = t => (t || '').replace(/[\s ۝٠-٩۰-۹۩]+$/u, '').trim();

        // setStatus: shows loading/error messages in the hint area (non-overlay context)
        const setStatus = (msg, isErr) => {
            if (!els.hint) return;
            els.hint.textContent = msg || '';
            els.hint.style.color = isErr ? 'var(--error-color)' : '';
            els.hint.style.opacity = msg ? '1' : '0.7';
        };

        // Fetch segment data for `surah` honouring the current split method +
        // sensitivity. Re-fetching for a param change keeps the same surah/audio
        // and ayah selection — only the phrase boundaries change.
        async function loadSurah(surah) {
            setStatus('جارٍ التحميل…');
            const mode = 'acoustic';
            const gap = 250;
            const reciter = getCurrentReciter();
            const fontType = getCurrentFontType();
            const resp = await fetch(`/api/memorization/${surah}?mode=${mode}&gap=${gap}&reciter=${encodeURIComponent(reciter)}&font_type=${encodeURIComponent(fontType)}`);
            if (!resp.ok) throw new Error('load failed');
            const surahChanged = loadedSurah !== surah || loadedReciter !== reciter;
            data = await resp.json();
            loadedSurah = surah;
            loadedReciter = reciter;
            if (surahChanged) {
                audio.src = data.audio_url;
                audio.load();
                populateAyahSelects();
            }
            renderVerseList();
            updateHint();
            setStatus('');
        }

        function populateAyahSelects() {
            const opts = data.verses.map(v => `<option value="${v.ayah}">${v.ayah}</option>`).join('');
            els.startAyah.innerHTML = opts;
            els.endAyah.innerHTML = opts;
            els.startAyah.value = data.verses[0].ayah;
            const defEnd = data.verses[Math.min(data.verses.length - 1, 4)].ayah; // first ~5 verses
            els.endAyah.value = defEnd;
        }

        // Live feedback: how the current method/sensitivity splits the selection.
        function updateHint() {
            if (!data) { els.hint.textContent = ''; return; }
            const vs = selectedVerses();
            let splitVerses = 0, totalPhrases = 0;
            vs.forEach(v => {
                const isLong = (v.end - v.start) > LONG_SEC && v.phrases.length > 1;
                if (isLong) { splitVerses++; totalPhrases += v.phrases.length; }
            });
            els.hint.textContent = splitVerses
                ? `سيُقسَّم ${splitVerses} من الآيات الطويلة إلى ${totalPhrases} مقطعًا`
                : 'لا توجد آيات طويلة للتقسيم في النطاق المختار';
        }

        function selectedVerses() {
            if (!data) return [];
            let a = parseInt(els.startAyah.value, 10);
            let b = parseInt(els.endAyah.value, 10);
            if (b < a) { const t = a; a = b; b = t; }
            return data.verses.filter(v => v.ayah >= a && v.ayah <= b);
        }

        // Build word-span HTML matching the main page's font rendering.
        // Uses quranTextData (global) when available; falls back to raw text.
        function buildVerseHTML(v) {
            const rawText = stripNum(v.text || '');
            // quranTextData is keyed by "surah:ayah"; it's loaded by the main page
            const entry = window.quranTextData && data
                ? (window.quranTextData[`${data.surah_number}:${v.ayah}`] || null)
                : null;
            const text = (entry && (entry.text || entry.raw_text)) || rawText;
            if (!text) return '';
            const words = text.trim().split(/\s+/).filter(Boolean);
            // Strip trailing verse-number ornament from last word
            if (words.length > 0) words[words.length - 1] = words[words.length - 1].replace(/[ۖ-ۭ٠-٩۰-۹]+$/, '').trim();
            const spans = words.filter(Boolean).map(w =>
                `<span class="word-base">${w}</span>`
            ).join(' ');
            return spans;
        }

        function renderVerseList() {
            const vs = selectedVerses();
            els.verseList.innerHTML = vs.map(v =>
                `<div class="memo-verse" data-ayah="${v.ayah}">` +
                `<span class="memo-vnum">${v.ayah}</span>` +
                `<span class="memo-verse-words">${buildVerseHTML(v)}</span></div>`
            ).join('');
        }

        // Build the circular-segmented-repetition schedule.
        function buildSchedule() {
            const vs = selectedVerses();
            const R = parseInt(els.verseReps.value, 10) || 1;
            const L = parseInt(els.linkReps.value, 10) || 1;
            const cumulative = els.cumulative.checked;
            const splitLong = els.splitLong.checked;
            const steps = [];
            const firstAyah = vs.length ? vs[0].ayah : null;

            vs.forEach((v, i) => {
                const dur = v.end - v.start;
                const usePhrases = splitLong && v.phrases.length > 1 && dur > LONG_SEC;
                if (usePhrases) {
                    v.phrases.forEach((p, j) => {
                        for (let r = 0; r < R; r++)
                            steps.push({ start: p.start, end: p.end, ayah: v.ayah,
                                label: `آية ${v.ayah} • مقطع ${j + 1}/${v.phrases.length}`, rep: r + 1, repTotal: R });
                        if (cumulative && j > 0)
                            steps.push({ start: v.phrases[0].start, end: p.end, ayah: v.ayah,
                                label: `آية ${v.ayah} • ربط المقاطع ١–${j + 1}`, rep: 1, repTotal: 1 });
                    });
                    steps.push({ start: v.start, end: v.end, ayah: v.ayah,
                        label: `آية ${v.ayah} • كاملة`, rep: 1, repTotal: 1 });
                } else {
                    for (let r = 0; r < R; r++)
                        steps.push({ start: v.start, end: v.end, ayah: v.ayah,
                            label: `آية ${v.ayah}`, rep: r + 1, repTotal: R });
                }
                if (cumulative && i > 0) {
                    for (let r = 0; r < L; r++)
                        steps.push({ start: vs[0].start, end: v.end, ayah: v.ayah,
                            label: `ربط الآيات ${firstAyah}–${v.ayah}`, rep: r + 1, repTotal: L });
                }
            });
            return steps;
        }

        function setOverlayStatus(msg) {
            if (els.overlayStatus) els.overlayStatus.textContent = msg || '';
        }
        function setOverlayProgress(pct) {
            if (els.overlayBar) els.overlayBar.style.width = `${pct}%`;
        }
        function showOverlay() {
            if (els.overlay) els.overlay.removeAttribute('hidden');
        }
        function hideOverlay() {
            if (els.overlay) els.overlay.setAttribute('hidden', '');
            setOverlayProgress(0);
            setOverlayStatus('');
            if (els.overlayVerse) els.overlayVerse.textContent = '';
        }

        function highlightAyah(ayah) {
            els.verseList.querySelectorAll('.memo-verse').forEach(el => {
                const on = parseInt(el.dataset.ayah, 10) === ayah;
                el.classList.toggle('memo-active', on);
                if (on) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            });
        }

        function updateOverlayVerse(ayah) {
            if (!els.overlayVerse || !data) return;
            const v = data.verses.find(x => x.ayah === ayah);
            if (!v) return;
            const entry = window.quranTextData
                ? (window.quranTextData[`${data.surah_number}:${ayah}`] || null)
                : null;
            const text = (entry && (entry.text || entry.raw_text)) || stripNum(v.text || '');
            els.overlayVerse.textContent = text;
        }

        // During multi-verse segments, follow the audio and navigate when a new
        // verse starts. Stored per-step so stop() can tear it down.
        let verseFollowerVerses = [];
        let verseFollowerCurrent = null;
        function verseFollowerTick() {
            if (!verseFollowerVerses.length || audio.paused) return;
            const t = audio.currentTime;
            const cur = verseFollowerVerses.find(v => t >= v.start - 0.05 && t < v.end + 0.05);
            if (!cur || cur.ayah === verseFollowerCurrent) return;
            verseFollowerCurrent = cur.ayah;
            updateOverlayVerse(cur.ayah);
            highlightAyah(cur.ayah);
            if (typeof window.__memoNavigate === 'function') {
                window.__memoNavigate(data.surah_number, cur.ayah).then(() => {
                    if (typeof window.__memoHighlightWithTimes === 'function') {
                        window.__memoHighlightWithTimes(cur.words || null);
                    }
                }).catch(() => {});
            }
        }

        function startMonitor() {
            stopMonitor();
            monitorId = setInterval(() => {
                if (pendingSeek || stepIdx < 0 || stepIdx >= schedule.length || audio.paused) return;
                verseFollowerTick();
                if (audio.currentTime >= schedule[stepIdx].end - EPS) nextStep();
            }, 80);
        }
        const stopMonitor = () => { if (monitorId) { clearInterval(monitorId); monitorId = null; } };

        function seekTo(t) {
            pendingSeek = true;
            const apply = () => { try { audio.currentTime = t; } catch (e) {} audio.play().catch(() => {}); };
            if (audio.readyState >= 1) apply();
            else audio.addEventListener('loadedmetadata', apply, { once: true });
        }
        audio.addEventListener('seeked', () => { pendingSeek = false; });

        let lastNavigatedAyah = null;
        function playStep(k) {
            stepIdx = k;
            if (k >= schedule.length) { finish(); return; }
            const seg = schedule[k];
            seekTo(seg.start);
            highlightAyah(seg.ayah);
            updateOverlayVerse(seg.ayah);
            const repTxt = seg.repTotal > 1 ? ` (${seg.rep}/${seg.repTotal})` : '';
            setOverlayStatus(`${seg.label}${repTxt} — ${k + 1}/${schedule.length}`);
            setOverlayProgress(Math.round((k / schedule.length) * 100));

            // All verses whose time window overlaps this segment (handles single-verse,
            // phrase, and cumulative-link steps uniformly).
            const segVerses = data.verses.filter(v =>
                v.start < seg.end + 0.1 && v.end > seg.start - 0.1
            );
            // Navigate to the FIRST verse of the segment so back-links land correctly.
            const navAyah = segVerses.length > 0 ? segVerses[0].ayah : seg.ayah;
            // Combined word timestamps for all overlapping verses.
            const allWords = segVerses.flatMap(v => v.words || []);

            // Arm verse-follower for multi-verse segments; single-verse = no-op.
            verseFollowerVerses = segVerses.length > 1 ? segVerses : [];
            verseFollowerCurrent = navAyah;

            if (navAyah !== lastNavigatedAyah && typeof window.__memoNavigate === 'function') {
                lastNavigatedAyah = navAyah;
                window.__memoNavigate(data.surah_number, navAyah).then(() => {
                    if (typeof window.__memoHighlightWithTimes === 'function') {
                        window.__memoHighlightWithTimes(allWords.length ? allWords : null);
                    }
                }).catch(() => {});
            } else {
                if (typeof window.__memoHighlightWithTimes === 'function') {
                    window.__memoHighlightWithTimes(allWords.length ? allWords : null);
                }
            }
        }
        const nextStep = () => playStep(stepIdx + 1);
        audio.addEventListener('ended', () => { if (stepIdx >= 0 && stepIdx < schedule.length) nextStep(); });

        function start() {
            schedule = buildSchedule();
            if (!schedule.length) { setStatus('لا توجد آيات محددة', true); return; }
            els.startBtn.disabled = true;
            closeModal();
            showOverlay();
            lastNavigatedAyah = null;
            if (els.overlayPause) els.overlayPause.classList.add('playing');
            startMonitor();
            playStep(0);
        }
        function togglePause() {
            if (audio.paused) {
                audio.play().catch(() => {});
                if (els.overlayPause) { els.overlayPause.classList.add('playing'); els.overlayPause.innerHTML = '<i class="fas fa-pause"></i>'; }
            } else {
                audio.pause();
                if (els.overlayPause) { els.overlayPause.classList.remove('playing'); els.overlayPause.innerHTML = '<i class="fas fa-play"></i>'; }
            }
        }
        function stop() {
            stopMonitor();
            audio.pause();
            stepIdx = -1;
            lastNavigatedAyah = null;
            verseFollowerVerses = [];
            verseFollowerCurrent = null;
            els.startBtn.disabled = false;
            hideOverlay();
            els.verseList.querySelectorAll('.memo-active').forEach(el => el.classList.remove('memo-active'));
            if (typeof window.__memoHighlightWithTimes === 'function') window.__memoHighlightWithTimes(null);
        }
        function finish() {
            stopMonitor();
            audio.pause();
            els.startBtn.disabled = false;
            setOverlayProgress(100);
            setOverlayStatus('تم الانتهاء ✓ بارك الله فيك');
            if (els.overlayPause) { els.overlayPause.classList.remove('playing'); els.overlayPause.innerHTML = '<i class="fas fa-pause"></i>'; }
            if (typeof window.__memoHighlightWithTimes === 'function') window.__memoHighlightWithTimes(null);
            setTimeout(hideOverlay, 3000);
        }

        async function openModal() {
            modal.classList.add('show');
            await loadReciters();
            const surah = getCurrentSurah();
            const reciter = getCurrentReciter();
            if (loadedSurah !== surah || loadedReciter !== reciter || !data) {
                setStatus('جارٍ تحضير الآيات…');
                try { await loadSurah(surah); }
                catch (e) { setStatus('تعذّر تحميل بيانات الحفظ', true); }
            }
        }
        // closeModal only hides the modal; stop() is separate so Start can close without stopping.
        function closeModal() { modal.classList.remove('show'); }

        // Re-fetch phrase data when the split method / sensitivity / reciter changes.
        let reloadTimer = null;
        async function reloadSegments() {
            if (loadedSurah == null) return;
            stop();
            try { await loadSurah(loadedSurah); }
            catch (e) { setStatus('تعذّر تحديث المقاطع', true); }
        }

        els.open && els.open.addEventListener('click', openModal);
        els.close && els.close.addEventListener('click', () => { closeModal(); stop(); });
        modal.addEventListener('click', e => { if (e.target === modal) { closeModal(); stop(); } });
        els.startBtn.addEventListener('click', start);
        els.overlayPause && els.overlayPause.addEventListener('click', togglePause);
        els.overlayStop  && els.overlayStop.addEventListener('click', stop);
        [els.startAyah, els.endAyah].forEach(s => s.addEventListener('change', () => { stop(); renderVerseList(); updateHint(); }));

        els.splitLong.addEventListener('change', updateHint);
        els.reciterSelect && els.reciterSelect.addEventListener('change', reloadSegments);
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready);
    else ready();
})();
