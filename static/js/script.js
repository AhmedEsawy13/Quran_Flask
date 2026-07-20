document.addEventListener('DOMContentLoaded', async () => {
    const elements = getElements();
    const { normalizeNonWarshWaqfText, stripEmbeddedWaqf } = window.AtharMushaf;
    const quranRequests = window.AtharMushaf.createRequestGate();
    const reciterAudioDataMap = {};
    let quranTextData;
    let currentSegments = [];
    let currentAyahData = null; // Cache for current ayah data
    let currentRepeatCount = 0; // Track current repeat count
    let maxRepeats = 1; // Track maximum repeats set by user
    let isRangeMode = false; // True while a verse range is playing
    let isScrubbingAudio = false; // True while the user is dragging the seek slider
    // Per-surah audio+word-timestamp bundle — one <audio> file per surah (same
    // source تثبيت/مُكْث already use), cached so ayah navigation seeks within
    // it instead of re-fetching a clip per ayah. {surah, reciter, audio_url,
    // verses: Map(ayahNumber -> {ayah, start, end, words})}
    let currentSurahAudio = null;
    // Surah-absolute seconds at which the current ayah/range-step should stop
    // (repeat or advance) — checked on 'timeupdate' since one shared file means
    // 'ended' only fires at the surah's very end, not per ayah.
    let ayahStopAt = null;
    let ayahBoundaryCallback = null;
    let ayahStopAtArmedAt = 0; // Date.now() when ayahStopAt was last (re)armed
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

    // دليل التلاوة now runs on مُكْث/تثبيت's own /api/waqf/<surah>/<ayah>
    // endpoint, which covers every installed reciter (same set as
    // reciter-select) — no more separate guide-only reciter roster or
    // name-key bridging.

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
        // Theme is applied by the shared AtharTheme engine (theme.js) on load.

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
        await populateReciterSelect();
        await loadQuranTextData();
        updateGlobalAyahToVerseKey();
    }

    async function populateReciterSelect() {
        try {
            const reciterList = await fetchData('/api/memorization-reciters');
            populateSelectOptions(reciterList, elements.reciterSelect, 'id', 'name_ar');
            // loadUserPreferences() ran before this select had any options, so its
            // elements.reciterSelect.value = savedReciter assignment was a silent
            // no-op — reapply the saved preference now that options exist.
            const savedReciter = localStorage.getItem('quranApp_reciter');
            if (savedReciter && Array.from(elements.reciterSelect.options).some((o) => o.value === savedReciter)) {
                elements.reciterSelect.value = savedReciter;
            }
            updateGuideButtonAvailability();
        } catch (error) {
            console.error('Error loading reciters:', error);
        }
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
            indopak_nastaleeq: ['الهندي'],
            indopak_nastaleeq_2: ['الهندي'],
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
                btn.setAttribute('aria-pressed', 'true');
                changed = true;
            }
        });
        if (changed) {
            localStorage.setItem('quranApp_mushafVersions',
                JSON.stringify(getSelectedMushafVersions()));
        }
        return changed;
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
                    btn.className = 'mushaf-pill athar-chip ' + colorCls;
                    if (saved.includes(version)) btn.classList.add('active');
                    btn.setAttribute('aria-pressed', btn.classList.contains('active') ? 'true' : 'false');
                    btn.addEventListener('click', () => {
                        const wasPlaying = !elements.audioElement.paused;
                        const savedTime = elements.audioElement.currentTime;
                        btn.classList.toggle('active');
                        btn.setAttribute('aria-pressed', btn.classList.contains('active') ? 'true' : 'false');
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
            audioSeekSlider: document.getElementById('audio-seek-slider'),
            audioCurrentTimeLabel: document.getElementById('audio-current-time'),
            audioDurationLabel: document.getElementById('audio-duration-time'),
            audioMuteButton: document.getElementById('audio-mute-toggle'),
        };
    }

    function addEventListeners() {
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
        // Mirror of the guard above: picking an end-ayah AT OR BEFORE the
        // current start left playRange() silently doing nothing (its own
        // startIdx <= endIdx check would fail with no feedback to the user)
        // — clamp start backward instead, same auto-correct the start select
        // already gets.
        elements.endAyahSelect.addEventListener('change', () => {
            const endIdx = elements.endAyahSelect.selectedIndex;
            if (elements.startAyahSelect.selectedIndex >= endIdx) {
                const prevIdx = Math.max(endIdx - 1, 0);
                elements.startAyahSelect.selectedIndex = prevIdx;
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
        // Keep the button's icon/label correct no matter WHAT started or
        // stopped playback — the custom button's own click handler, the
        // native <audio controls> bar rendered alongside it, or a media key.
        // Bound on the audio element itself (not the button), so this stays
        // correct through range-mode's own click-handler swap too (see
        // playRange()/cleanupRangeMode(), which only replace the button's
        // click listener, never these).
        elements.audioElement.addEventListener('play', updatePlayPauseButton);
        elements.audioElement.addEventListener('pause', updatePlayPauseButton);

        // Unified player's seek bar + time labels + mute button — replaces
        // the native <audio controls> UI that used to render separately.
        if (elements.audioSeekSlider) {
            elements.audioElement.addEventListener('timeupdate', updateAudioSeekUI);
            elements.audioElement.addEventListener('loadedmetadata', updateAudioSeekUI);
            elements.audioElement.addEventListener('durationchange', updateAudioSeekUI);
            elements.audioSeekSlider.addEventListener('input', () => {
                isScrubbingAudio = true;
                const duration = elements.audioElement.duration;
                if (isFinite(duration) && duration > 0 && elements.audioCurrentTimeLabel) {
                    const previewTime = (elements.audioSeekSlider.value / 1000) * duration;
                    elements.audioCurrentTimeLabel.textContent = formatAudioTime(previewTime);
                }
            });
            elements.audioSeekSlider.addEventListener('change', () => {
                const duration = elements.audioElement.duration;
                if (isFinite(duration) && duration > 0) {
                    elements.audioElement.currentTime = (elements.audioSeekSlider.value / 1000) * duration;
                }
                isScrubbingAudio = false;
                // The seek bar spans the whole surah now — a manual scrub is
                // the user explicitly taking control, so drop the current
                // ayah's auto-stop/repeat boundary rather than yanking
                // playback back to it on the next timeupdate tick.
                if (!isRangeMode) clearAyahStopAt();
            });
        }
        if (elements.audioMuteButton) {
            elements.audioMuteButton.addEventListener('click', () => {
                elements.audioElement.muted = !elements.audioElement.muted;
                updateAudioMuteButton();
            });
        }

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
        const mutashabihatBtn = document.getElementById('show-mutashabihat');
        if (mutashabihatBtn) mutashabihatBtn.addEventListener('click', toggleMutashabihat);
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
                legendToggle.setAttribute('aria-expanded', hidden ? 'true' : 'false');
            }
        });

        const tajweedLegendToggle = document.getElementById('tajweed-legend-toggle');
        if (tajweedLegendToggle) tajweedLegendToggle.addEventListener('click', () => {
            const legend = document.getElementById('tajweed-legend');
            if (!legend) return;
            const hidden = legend.hasAttribute('hidden');
            if (hidden) { legend.removeAttribute('hidden'); } else { legend.setAttribute('hidden', ''); }
            tajweedLegendToggle.classList.toggle('active', hidden);
            tajweedLegendToggle.setAttribute('aria-expanded', hidden ? 'true' : 'false');
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
                    waqfTableBtn.setAttribute('aria-pressed', 'true');
                    renderWaqfVerseTable();
                } else {
                    tableContainer.setAttribute('hidden', '');
                    waqfTableBtn.classList.remove('active');
                    waqfTableBtn.setAttribute('aria-pressed', 'false');
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
        // /api/waqf/<surah>/<ayah> covers every installed reciter (same set as
        // reciter-select), so the guide is always available now — the only
        // per-verse "no data" case (e.g. a verse with no attested stops at all)
        // is handled inside fetchAndBuildRecitationGuide() itself.
        const guideBtn = document.getElementById('show-recitation-guide');
        if (!guideBtn) return;
        guideBtn.removeAttribute('data-guide-unavailable');
        guideBtn.title = 'دليل التلاوة وفق علامات الوقف';
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

    // IndoPak waqf ruling marks — stripped from word text so they render as
    // .waqf-stack overlays (same pattern as المدينة / الشمرلي), not as inline
    // combining glyphs or standalone between-word tokens.
    // Keeps verse-end circle ۟ (U+06DF), structural marks (U+06E0–U+06E4), and
    // PUA verse-number glyphs (U+F500+) so the ayah seal still renders.
    const INDOPAK_INLINE_WAQF_STRIP = /[\u0614\u0615\u0617\u06D6-\u06DC\u06EA-\u06EC\u06ED]/g;

    function getDisplayedAyahText(verseEntry = {}, fallbackText = '') {
        const font = elements.quranTextSelect.value;
        const isIndoPak = font === 'indopak_nastaleeq' || font === 'indopak_nastaleeq_2';

        if (isIndoPak) {
            // Prefer aligned `text` (mid-verse waqf-only tokens already removed at
            // boot) then raw_text. Always strip ruling marks and drop tokens that
            // become empty (e.g. standalone "ۛۖۚ") so no gap-spaces remain.
            const base = verseEntry.text || verseEntry.raw_text || fallbackText || '';
            return base
                .split(/\s+/)
                .map(tok => tok.replace(INDOPAK_INLINE_WAQF_STRIP, ''))
                .filter(Boolean)
                .join(' ');
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

    // Fetch + cache one surah's audio_url + per-ayah word timestamps (same
    // /api/memorization endpoint تثبيت/مُكْث already use). No-op if the
    // requested surah+reciter is already the cached one — ayah navigation
    // within a surah just seeks, no re-fetch. Sets audio.src only when the
    // surah or reciter actually changed.
    async function ensureSurahAudioLoaded(surahNumber, reciterId) {
        const surahNum = parseInt(surahNumber, 10);
        if (currentSurahAudio && currentSurahAudio.surah === surahNum && currentSurahAudio.reciter === reciterId) {
            return currentSurahAudio;
        }
        const data = await fetchData(`/api/memorization/${surahNum}?reciter=${encodeURIComponent(reciterId)}`);
        const verses = new Map();
        (data.verses || []).forEach((v) => verses.set(v.ayah, v));
        currentSurahAudio = { surah: surahNum, reciter: reciterId, audio_url: data.audio_url, verses };
        if (elements.audioElement.src !== data.audio_url) {
            elements.audioElement.src = data.audio_url;
            resetAudioSeekUI();
        }
        return currentSurahAudio;
    }

    // One segment per word (already surah-absolute seconds) — matches the
    // {start_word_index, end_word_index, start_time, end_time} shape
    // mapSegmentsToWords()/highlightWords() already consume, unchanged.
    function buildAyahSegments(verse) {
        if (!verse || !Array.isArray(verse.words)) return [];
        return verse.words.map(([idx, startSec, endSec]) => ({
            start_word_index: idx, end_word_index: idx,
            start_time: Math.round(startSec * 1000), end_time: Math.round(endSec * 1000),
        }));
    }

    // Every ayahStopAt assignment goes through here so the grace-period guard
    // (see the 'timeupdate' listener below) can never be forgotten at a call
    // site. Needed because seeking elements.audioElement.currentTime back to
    // an ayah's start doesn't apply instantly — the very next 'timeupdate'
    // tick can still report the pre-seek currentTime, which would otherwise
    // immediately re-trigger the boundary we just reset and fire the repeat
    // callback multiple times per real loop.
    function setAyahStopAt(seconds, callback) {
        ayahStopAt = seconds;
        ayahBoundaryCallback = callback;
        ayahStopAtArmedAt = Date.now();
    }

    function clearAyahStopAt() {
        ayahStopAt = null;
        ayahBoundaryCallback = null;
    }

    async function loadQuranData() {
        const request = quranRequests.next();
        const surahNumber = elements.surahSelect.value;
        const ayahNumber = elements.ayahSelect.value;
        if (!ayahNumber) return;
    
        try {
            const font = elements.quranTextSelect.value;
            let selectedVersions = getSelectedMushafVersions();

            // الشمرلي's own waqf marks can't be embedded inline in the (borrowed
            // qpc_hafs) text, so always request them regardless of which mushaf
            // pills the user has checked — matches the "original" mode's need to
            // show شمرلي's own symbols even when nothing else is selected.
            if (font === 'shamarly' && !selectedVersions.includes('الشمرلي')) {
                selectedVersions = ['الشمرلي', ...selectedVersions];
            }

            // Tell the backend which text source we're using so it can return
            // the correct embedded waqf symbols (e.g. الهندي for IndoPak fonts).
            const source = font === 'indopak_nastaleeq' || font === 'indopak_nastaleeq_2'
                ? 'indopak_nastaleeq' : '';
            const query = window.AtharMushaf.buildQuery({ versions: selectedVersions, source });
            const ayahData = await fetchData(`/api/surahs/${surahNumber}/ayahs/${ayahNumber}${query}`);
            if (!quranRequests.isCurrent(request)) return false;
            const verseKey = `${surahNumber}:${ayahNumber}`;
            const globalAyahNumber = ayahData.id;
            if (!globalAyahNumber) throw new Error(`No global Ayah number found for Surah ${surahNumber}, Ayah ${ayahNumber}`);

            const reciter = elements.reciterSelect.value;
            const surahAudio = await ensureSurahAudioLoaded(surahNumber, reciter);
            if (!quranRequests.isCurrent(request)) return false;
            const verse = surahAudio.verses.get(parseInt(ayahNumber, 10));
            if (!verse) throw new Error('Reciter audio not found for this ayah');
            currentAyahData = ayahData;
            elements.audioElement.currentTime = verse.start;
            if (!isRangeMode) setAyahStopAt(verse.end, handleAyahEndedNormal);

            // Use already cached quranTextData instead of making redundant API call.
            const _verseEntry = quranTextData?.[verseKey] || {};
            const ayahText = getDisplayedAyahText(_verseEntry, ayahData.text || ayahData.raw_text || '');

            currentSegments = buildAyahSegments(verse);
            displayQuranicText(ayahText, currentSegments, ayahData.waqf_symbols || []);
            if (font === 'shamarly') await applyShamarlyGlyphs(surahNumber, ayahNumber);
            if (!quranRequests.isCurrent(request)) return false;
            renderWaqfVerseTable();
            displayTransliteration(ayahData.transliteration);
            await maybeRefreshTafseer(surahNumber, ayahNumber);
            if (!quranRequests.isCurrent(request)) return false;
            await maybeRefreshEerab(surahNumber, ayahNumber);
            if (!quranRequests.isCurrent(request)) return false;
            await maybeRefreshTajweed(surahNumber, ayahNumber);
            if (!quranRequests.isCurrent(request)) return false;
            await maybeRefreshMutashabihat(surahNumber, ayahNumber);
            if (!quranRequests.isCurrent(request)) return false;
            // Only display word meanings if they should be visible
            if (elements.wordMeaningVisible) {
                displayWordMeanings(ayahData.word_meanings_ordered || ayahData.word_meanings || {}, ayahText);
            } else {
                elements.wordMeaningContainer.innerHTML = '';
            }
            updatePlayPauseButton();

            // Refresh recitation guide if visible
            const guideContainer = document.getElementById('recitation-guide-container');
            if (guideContainer && guideContainer.style.display !== 'none') {
                await fetchAndBuildRecitationGuide();
                if (!quranRequests.isCurrent(request)) return false;
            }

            // Save current position to localStorage
            saveUserPreferences();
            return true;
        } catch (error) {
            if (!quranRequests.isCurrent(request)) return false;
            handleError('Error loading Quran data:', error, elements.quranTextContainer, 'خطأ في تحميل البيانات. يرجى المحاولة مرة أخرى لاحقًا.');
            return false;
        }
    }

    // الشمرلي enhancement: the generic pipeline already rendered this ayah's
    // words as plain (qpc_hafs-identical) text via displayQuranicText(). This
    // upgrades whichever words have a genuine page-local Shemrly glyph
    // available (~200/521 pages ship a font) — every other word is left
    // exactly as the generic pipeline rendered it. `/api/shamarly/ayah/...` is
    // purely positional (surah/ayah/word_index → page → font → codepoint), so
    // it needs no mushaf_version query — waqf-symbol overlay is already
    // handled generically via currentAyahData.waqf_symbols.
    async function applyShamarlyGlyphs(surahNumber, ayahNumber) {
        let payload;
        try {
            payload = await fetchData(`/api/shamarly/ayah/${surahNumber}/${ayahNumber}`);
        } catch (error) {
            return; // plain text already rendered — nothing to enhance
        }
        const allWords = Array.isArray(payload?.words) ? payload.words : [];
        // quran_script.db keeps the ayah number as its own trailing "word" entry,
        // while the generic pipeline's qpc_hafs-based tokenization glues it (via
        // NBSP) onto the last real word instead — so it never appears as a
        // separate .word-token. Pull it out before aligning the rest 1:1 against
        // .word-token elements, but hold onto it: it carries its own page-local
        // ornament glyph, which must be re-attached to that same token below
        // instead of being silently erased by the word substitution.
        const ayahNumWord = allWords.find((w) => /^[٠-٩]+$/.test((w?.text_original || '').trim()));
        const words = allWords.filter((w) => w !== ayahNumWord);
        const wordEls = elements.quranTextContainer.querySelectorAll(':scope > .word-token');
        // Alignment guard: both lists must describe the same ayah word-for-word
        // (confirmed same underlying qpc_hafs-equivalent text) — if they don't
        // line up for some reason, skip the enhancement rather than mismatch glyphs.
        if (!words.length || words.length !== wordEls.length) return;

        // A verse can span two font-bearing pages; load every referenced page's
        // font before touching any DOM, so words don't flash plain-then-glyph.
        const pages = Array.isArray(payload?.font_pages) ? payload.font_pages : [];
        await Promise.all(pages.map((p) => ensureShamarlyFontLoaded(shamarlyFontName(p))));

        words.forEach((word, index) => {
            if (!word?.glyph_page) return;
            const wordEl = wordEls[index];
            const baseEl = wordEl?.querySelector(':scope > .word-content > .word-base');
            if (!baseEl) return;
            // The ayah-number suffix already sitting in baseEl's current text
            // (glued on via NBSP by the generic pipeline) would otherwise be wiped
            // out by the textContent overwrite below — carry it forward. Upgrade
            // it to its own page-local ornament glyph only when that glyph is on
            // the SAME page as this word's own glyph (mixed-page fonts would
            // render the wrong page's cmap); otherwise keep the plain digit.
            let suffix = '';
            const isLastWord = index === words.length - 1;
            if (isLastWord) {
                const existingSuffix = (baseEl.textContent || '').match(/ [٠-٩]+$/);
                suffix = existingSuffix ? existingSuffix[0] : '';
                if (ayahNumWord?.glyph_char && ayahNumWord.glyph_page === word.glyph_page) {
                    suffix = ' ' + ayahNumWord.glyph_char;
                }
            }
            baseEl.textContent = (word.text || baseEl.textContent.replace(/ [٠-٩]+$/, '')) + suffix;
            wordEl.style.fontFamily = `'${shamarlyFontName(word.glyph_page)}', 'UthmanicHafs', serif`;
            wordEl.dataset.shamarlyGlyph = '1';
        });
    }

    function shamarlyFontName(pageNumber) {
        return `Shemrly-Page${String(pageNumber).padStart(3, '0')}`;
    }

    async function ensureShamarlyFontLoaded(fontName) {
        if (!fontName || loadedShamarlyFonts.has(fontName)) {
            return;
        }
        try {
            const font = new FontFace(fontName, `url('/static/fonts/${fontName}.woff2') format('woff2')`);
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
        const request = quranRequests.next();
        const surahNumber = elements.surahSelect.value;
        const ayahNumber = elements.ayahSelect.value;
        if (!ayahNumber) return;

        try {
            const _fontNow = elements.quranTextSelect.value;
            let ayahData = currentAyahData;

            // Use cached data if available, otherwise fetch
            if (!ayahData || ayahData.surah_number !== parseInt(surahNumber) || ayahData.ayah_number !== parseInt(ayahNumber)) {
                let _vers = getSelectedMushafVersions();
                if (_fontNow === 'shamarly' && !_vers.includes('الشمرلي')) {
                    _vers = ['الشمرلي', ..._vers];
                }
                let source = '';
                if (_fontNow === 'indopak_nastaleeq' || _fontNow === 'indopak_nastaleeq_2') {
                    source = 'indopak_nastaleeq';
                } else if (_fontNow === 'amiri_quran') {
                    source = 'amiri_quran';
                }
                const query = window.AtharMushaf.buildQuery({ versions: _vers, source });
                ayahData = await fetchData(`/api/surahs/${surahNumber}/ayahs/${ayahNumber}${query}`);
                if (!quranRequests.isCurrent(request)) return false;
                currentAyahData = ayahData;
            }

            const verseKey = `${surahNumber}:${ayahNumber}`;
            // Use already cached quranTextData instead of making redundant API call.
            const _verseEntry = quranTextData?.[verseKey] || {};
            const ayahText = getDisplayedAyahText(_verseEntry, ayahData.text || ayahData.raw_text || '');
            displayQuranicText(ayahText, currentSegments, ayahData.waqf_symbols || []);
            if (_fontNow === 'shamarly') await applyShamarlyGlyphs(surahNumber, ayahNumber);
            if (!quranRequests.isCurrent(request)) return false;
            renderWaqfVerseTable();
            displayTransliteration(ayahData.transliteration);
            await maybeRefreshTafseer(surahNumber, ayahNumber);
            if (!quranRequests.isCurrent(request)) return false;
            await maybeRefreshEerab(surahNumber, ayahNumber);
            if (!quranRequests.isCurrent(request)) return false;
            await maybeRefreshTajweed(surahNumber, ayahNumber);
            if (!quranRequests.isCurrent(request)) return false;
            await maybeRefreshMutashabihat(surahNumber, ayahNumber);
            if (!quranRequests.isCurrent(request)) return false;
            if (elements.wordMeaningVisible) {
                displayWordMeanings(ayahData.word_meanings_ordered || ayahData.word_meanings || {}, ayahText);
            } else {
                elements.wordMeaningContainer.innerHTML = '';
            }
            return true;
        } catch (error) {
            if (!quranRequests.isCurrent(request)) return false;
            handleError('Error updating Quran text:', error, elements.quranTextContainer, 'خطأ في تحديث النص. يرجى المحاولة مرة أخرى لاحقًا.');
            return false;
        }
    }

    function displayQuranicText(text, segments, waqfSymbols = []) {
        elements.quranTextContainer.style.fontFamily = '';
        const words = window.AtharMushaf.mergeWaqfOnlyTokens(
            String(text || '').split(/\s+/).filter(Boolean)
        );
        const wordIndexToSegmentMap = new Map();

        // filterWaqfByMode() adds each font's own printed layer (الهندي /
        // الشمرلي) as overlays — word text stays clean for all fonts.
        const activeSymbols = filterWaqfByMode(waqfSymbols);

        const waqfByToken = window.AtharMushaf.indexWaqfEntries(activeSymbols, words);

        // Map segments to words first, before creating word elements
        if (Array.isArray(segments)) {
            mapSegmentsToWords(segments, wordIndexToSegmentMap);
        } else {
            console.error('Invalid segments format:', segments);
        }

        const wordElements = window.AtharMushaf.renderWordRun(elements.quranTextContainer, words, {
            wordClass: 'word-token', separator: ' ',
            renderWord: (wordElement, context) => {
                renderReaderWord(wordElement, context.raw, context.index, wordIndexToSegmentMap);
            },
            decorateWord: (wordElement, context) => {
                const entries = waqfByToken.get(context.index);
                if (entries) appendWaqfEntries(wordElement, entries);
            },
        });

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
        // Shemrly / IndoPak: the mushaf's own marks are the "original" overlay
        // layer (word text stays clean — same pattern as المدينة stacks).
        const isShamarly = document.body.dataset.fontType === 'shamarly';
        if (!Array.isArray(symbols)) return symbols;
        if (mode === 'none') return [];
        if (mode === 'original') {
            if (isShamarly) return symbols.filter(s => (s.version || '') === 'الشمرلي');
            if (isIndoPak) return symbols.filter(s => (s.version || '') === 'الهندي');
            return [];
        }
        const selSet = new Set(getSelectedMushafVersions());
        if (mode === 'selected') {
            return symbols.filter(s => selSet.has(s.version || ''));
        }
        // 'both' — selected overlays + each font's own printed layer.
        return symbols.filter(s => {
            const v = s.version || '';
            if (isShamarly && v === 'الشمرلي') return true;
            if (isIndoPak && v === 'الهندي') return true;
            return selSet.has(v);
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

        const indopakSymFont = "'IndoPakNastaleeq2', serif";

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

        const ORDER = ['المدينة الجديد', 'المدينة القديم', 'الشمرلي', 'الأزهر', 'ورش', 'الحصري', 'الهندي'];
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
        '\u06DD': { meaning: 'رأس آية — نهاية الآية في عدّ ورش وموضع الوقف' },
        // Standard Unicode waqf glyphs (after normalisation)
        '\u06D6': { meaning: 'صلى — الأفضل الوصل' },
        '\u06D7': { meaning: 'قلى — الأفضل الوقف' },
        '\u06D8': { meaning: 'م — وقف لازم' },
        '\u06D9': { meaning: 'لا — لا يجوز الوقف' },
        '\u06DA': { meaning: 'ج — جائز الوقف والوصل' },
        '\u06DB': { meaning: 'ع — وقف معانقة' },
    };

    // IndoPak (الهندي): DB stores Unicode small-high marks; ط/ز/م… are the
    // traditional letter names readers know. Keep letter keys as aliases.
    const WAQF_INFO_HINDI = {
        '\u0615': { meaning: 'ؕ — ط المطلق (مصحف هندي)' },
        '\u0617': { meaning: 'ؗ — ز المجوَّز لوجه (مصحف هندي)' },
        '\u0614': { meaning: 'ؔ — قف ولا تصل (مصحف هندي)' },
        '\u06D6': { meaning: 'ۖ — ص المرخّص لضرورة (مصحف هندي)' },
        '\u06D7': { meaning: 'ۗ — قلى، الأفضل الوقف (مصحف هندي)' },
        '\u06D8': { meaning: 'ۘ — م اللازم (مصحف هندي)' },
        '\u06D9': { meaning: 'ۙ — لا، لا يجوز الوقف (مصحف هندي)' },
        '\u06DA': { meaning: 'ۚ — ج الجائز (مصحف هندي)' },
        '\u06DB': { meaning: 'ۛ — ع المعانقة (مصحف هندي)' },
        '\u06EA': { meaning: '۪ — علامة وقف تحتية (مصحف هندي)' },
        '\u06EB': { meaning: '۫ — علامة وقف فوقية (مصحف هندي)' },
        '\u06EC': { meaning: '۬ — علامة وقف دائرية (مصحف هندي)' },
        '\u06DF': { meaning: '۟ — رأس آية (ليس حكم وقف)' },
        '\u06E0': { meaning: '۠ — رأس خمس / ركوع (ليس حكم وقف)' },
        // Traditional letter aliases (legend / older docs)
        'ط':  { meaning: 'ؕ — ط المطلق (مصحف هندي)' },
        'ز':  { meaning: 'ؗ — ز المجوَّز لوجه (مصحف هندي)' },
        'م':  { meaning: 'ۘ — م اللازم (مصحف هندي)' },
        'ص':  { meaning: 'ۖ — ص المرخّص لضرورة (مصحف هندي)' },
        'ج':  { meaning: 'ۚ — ج الجائز (مصحف هندي)' },
        'لا': { meaning: 'ۙ — لا، لا يجوز الوقف (مصحف هندي)' },
    };

    function getWaqfInfo(rawSymbol, version = '') {
        const key = (rawSymbol || '').trim();
        if (version === 'الهندي' && WAQF_INFO_HINDI[key]) return WAQF_INFO_HINDI[key];
        return WAQF_INFO[key] || WAQF_INFO_HINDI[key] || { meaning: key };
    }


    // MUSHAF_COLOR_MAP and getMushafColorClass defined earlier near loadMushafVersions

    function appendWaqfEntries(container, entriesOrText, fallbackVersion = '') {
        window.AtharMushaf.appendWaqfEntries(container, entriesOrText, {
            fallbackVersion,
            stackPosition: 'prepend',
            classFor: version => getMushafColorClass(version),
            titleFor: (symbol, version, data) => {
                const versionLabel = version ? `مصحف: ${version}` : '';
                const info = getWaqfInfo(symbol.trim(), version);
                const symbolLabel = info.meaning || data.title.trim();
                return [versionLabel, symbolLabel].filter(Boolean).join(' | ');
            },
        });
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
                const active = btn.dataset.mode === mode;
                btn.classList.toggle('active', active);
                btn.setAttribute('aria-pressed', active ? 'true' : 'false');
            });
        }

        // Trigger a full re-render so the verse text variant and overlay symbols
        // both reflect the new mode. Skip if we're still booting (no ayah loaded).
        if (currentAyahData && elements.ayahSelect && elements.ayahSelect.value) {
            loadQuranData();
        }
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


    function getCurrentKhattJustifyValue() {
        const raw = elements.khattJustifySlider?.value ?? localStorage.getItem('quranApp_khattJustify') ?? '50';
        const parsed = parseInt(raw, 10);
        return Number.isFinite(parsed) ? Math.max(0, Math.min(100, parsed)) : 50;
    }

    // المدينة القديم (oldmadinafont) doesn't implement the jt/dc/kt tags the
    // previous alshamiyafont-based file used for this slider — it exposes
    // character-variant alternates instead (cv01-cv04, cv10-cv19; cv05-cv09
    // aren't defined in this font).
    function getKhattFeatureSequence() {
        return ['cv01', 'cv02', 'cv03', 'cv04', 'cv10', 'cv11', 'cv12', 'cv13', 'cv14', 'cv15', 'cv16', 'cv17', 'cv18', 'cv19'];
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
            // شمرلي page-local glyph substitution (applyShamarlyGlyphs) already
            // set this word's text/font — dataset.textOriginal/textClean is the
            // plain qpc_hafs text underneath, not what should be displayed.
            if (item.wordEl.dataset.shamarlyGlyph === '1') return;
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
        const enabled = eerabContainer.style.display !== 'none';
        eerabButton.textContent = enabled ? 'إخفاء الإعراب' : 'الإعراب';
        eerabButton.classList.toggle('active', enabled);
        eerabButton.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    }

    // ── المتشابهات (similar verses, للحفظ) ────────────────────────────────────
    const _mutashabihatCache = {};   // verse_key → API payload

    async function toggleMutashabihat() {
        const container = document.getElementById('mutashabihat-container');
        if (!container) return;
        const isHidden = container.style.display === 'none';
        container.style.display = isHidden ? 'block' : 'none';
        updateMutashabihatButton();
        if (isHidden) {
            const surah = elements.surahSelect.value;
            const ayah = elements.ayahSelect.value;
            if (surah && ayah) await fetchAndDisplayMutashabihat(surah, ayah);
        }
    }

    async function fetchAndDisplayMutashabihat(surahNumber, ayahNumber) {
        const key = `${surahNumber}:${ayahNumber}`;
        const el = document.getElementById('mutashabihat-text');
        if (_mutashabihatCache[key]) { displayMutashabihat(_mutashabihatCache[key]); return; }
        if (el) el.innerHTML = '<p class="mutashabihat-empty">…جارٍ البحث</p>';
        try {
            const data = await fetchData(`/api/mutashabihat/${surahNumber}/${ayahNumber}`);
            _mutashabihatCache[key] = data;
            displayMutashabihat(data);
        } catch (e) {
            console.error('Error loading mutashabihat:', e);
            if (el) el.innerHTML = '<p class="mutashabihat-empty">تعذّر تحميل المتشابهات.</p>';
        }
    }

    async function maybeRefreshMutashabihat(surahNumber, ayahNumber) {
        const container = document.getElementById('mutashabihat-container');
        if (container && container.style.display !== 'none') {
            await fetchAndDisplayMutashabihat(surahNumber, ayahNumber);
        }
    }

    // Render a candidate verse word-by-word from the diff opcodes: words that
    // are 'equal' to the query are plain, everything else (replace/insert) is
    // flagged as a divergence — that is precisely the spot a memorizer slips.
    function _renderMutashabihatWords(words, opcodes) {
        const cls = new Array(words.length).fill('m');   // 'm' = matches query
        for (const [tag, , , j1, j2] of opcodes) {
            if (tag !== 'equal') for (let j = j1; j < j2; j++) cls[j] = 'd'; // d = differs
        }
        return words.map((w, j) =>
            `<span class="mut-w${cls[j] === 'd' ? ' mut-diff' : ''}">${w}</span>`
        ).join(' ');
    }

    function displayMutashabihat(data) {
        const el = document.getElementById('mutashabihat-text');
        if (!el) return;
        const matches = (data && data.matches) || [];
        if (!matches.length) {
            el.innerHTML = '<p class="mutashabihat-empty">لا توجد آيات متشابهة بدرجة معتبرة لهذه الآية.</p>';
            return;
        }
        const surahName = (n) => {
            const opt = elements.surahSelect?.querySelector(`option[value="${n}"]`);
            return opt ? opt.textContent.replace(/^\s*\d+\s*[-.]?\s*/, '').trim() : `سورة ${n}`;
        };
        const runWord = (n) => n <= 2 ? 'كلمتان' : n <= 10 ? 'كلمات' : 'كلمة';
        const html = matches.map(m => {
            const ref = `${surahName(m.surah)} ${m.surah}:${m.ayah}`;
            const badge = m.near_duplicate
                ? '<span class="mut-badge mut-badge-dup" title="آية تكاد تطابق هذه الآية">شبه مطابقة</span>'
                : `<span class="mut-badge" title="أطول تتابع لفظي مشترك">${m.longest_run} ${runWord(m.longest_run)} متتالية</span>`;
            return `<button class="mutashabihat-item" type="button" data-s="${m.surah}" data-a="${m.ayah}"
                        title="انتقل إلى ${ref}">
                <span class="mut-head">
                    <span class="mut-ref">${ref}</span>
                    <span class="mut-meta">${badge}</span>
                </span>
                <span class="mut-verse" dir="rtl">${_renderMutashabihatWords(m.words, m.opcodes)}</span>
            </button>`;
        }).join('');
        el.innerHTML = html;
        el.querySelectorAll('.mutashabihat-item').forEach(btn => {
            btn.addEventListener('click', () => {
                const s = btn.dataset.s, a = btn.dataset.a;
                if (elements.surahSelect.value !== s) {
                    elements.surahSelect.value = s;
                    elements.surahSelect.dispatchEvent(new Event('change'));
                    setTimeout(() => { elements.ayahSelect.value = a; elements.ayahSelect.dispatchEvent(new Event('change')); }, 250);
                } else {
                    elements.ayahSelect.value = a;
                    elements.ayahSelect.dispatchEvent(new Event('change'));
                }
            });
        });
    }

    function updateMutashabihatButton() {
        const btn = document.getElementById('show-mutashabihat');
        const container = document.getElementById('mutashabihat-container');
        if (!btn || !container) return;
        const on = container.style.display !== 'none';
        btn.classList.toggle('active', on);
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        btn.innerHTML = on
            ? '<i class="fas fa-clone"></i> إخفاء المتشابهات'
            : '<i class="fas fa-clone"></i> المتشابهات';
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
                // شمرلي page-local glyph substitution: baseEl currently holds an
                // opaque glyph char, not the real letter — colouring it would
                // both look wrong and clobber the substitution. Skipped here
                // (not filtered out above) so tajweedWords' index alignment with
                // the rest of the ayah's real words stays correct.
                if (item.wordEl.dataset.shamarlyGlyph === '1') return;
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
        if (!transliterationButton || !transliterationContainer) return;
        const enabled = transliterationContainer.style.display !== 'none';
        if (!enabled) {
            transliterationButton.textContent = 'عرض النطق الحرفي ';
        } else {
            transliterationButton.textContent = 'اخفاء النطق الحرفي';
        }
        transliterationButton.classList.toggle('active', enabled);
        transliterationButton.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    }

    function updateTafseerButton() {
        const tafseerButton = document.getElementById('show-tafseer');
        const tafseerContainer = document.getElementById('tafseer-container');
        if (!tafseerButton || !tafseerContainer) return;
        const enabled = tafseerContainer.style.display !== 'none';
        if (!enabled) {
            tafseerButton.textContent = 'عرض التفسير';
        } else {
            tafseerButton.textContent = 'اخفاء التفسير';
        }
        tafseerButton.classList.toggle('active', enabled);
        tafseerButton.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    }

    function updateWordMeaningButton() {
        if (!elements.toggleWordMeaningButton) return;
        if (elements.wordMeaningVisible) {
            elements.toggleWordMeaningButton.textContent = 'اخفاء غريب الكلمات';
        } else {
            elements.toggleWordMeaningButton.textContent = 'عرض غريب الكلمات';
        }
        elements.toggleWordMeaningButton.classList.toggle('active', elements.wordMeaningVisible);
        elements.toggleWordMeaningButton.setAttribute('aria-pressed', elements.wordMeaningVisible ? 'true' : 'false');
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
            guideBtn.setAttribute('aria-pressed', isHidden ? 'true' : 'false');
            const btnText = guideBtn.querySelector('span');
            if (btnText) btnText.textContent = isHidden ? 'إخفاء دليل التلاوة' : 'دليل التلاوة';
        }

        if (isHidden) {
            await fetchAndBuildRecitationGuide();
            guideContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } else {
            clearGuidePlaying();
        }
    }

    const guideToAr = n => String(n).replace(/[0-9]/g, d => '٠١٢٣٤٥٦٧٨٩'[d]);
    const isGuideYoutubeUrl = url => /youtube\.com|youtu\.be/.test(url || '');

    // Printed-mushaf waqf symbols → meaning + glyph (data comes from مُكْث's
    // /api/waqf; the look here is this page's own — same styling the old
    // positions.db-powered guide used, not مُكْث's own wq-* design).
    const GUIDE_WAQF_MEANING = {
        'م': 'وقف لازم', 'لا': 'لا وقف', 'ق': 'الوقف أولى', 'ص': 'الوصل أولى',
        'ج': 'جائز', 'س': 'سكتة', 'ع': 'معانقة',
    };
    const guideSymName = s => GUIDE_WAQF_MEANING[s] || s;
    const guideWaqfGlyph = normalizeNonWarshWaqfText;

    /* ── segment preview audio ────────────────────────────────────────────
       Reciters-comparison cards can show a DIFFERENT reciter than the one
       currently loaded in the main player, so segment previews play through
       a small dedicated <audio> instead of elements.audioElement — this never
       disturbs the user's actual listening position. Pauses the main player
       first so the two never sound at once. YouTube-sourced reciters (محمد
       برهجي) have no play button here — the main page has no IFrame adapter. */
    const guideAudio = new Audio();
    guideAudio.preload = 'none';
    let guideAudioStopAt = null, guidePlayingBtn = null, guidePollTimer = null;

    function clearGuidePlaying() {
        if (guidePlayingBtn) {
            const i = guidePlayingBtn.querySelector('i');
            if (i) i.className = guidePlayingBtn.dataset.icon || 'fas fa-play';
            guidePlayingBtn.classList.remove('guide-seg-playing');
        }
        guidePlayingBtn = null;
        if (guidePollTimer) { clearInterval(guidePollTimer); guidePollTimer = null; }
        guideAudioStopAt = null;
        document.querySelectorAll('.guide-segment.guide-segment-active').forEach(el => el.classList.remove('guide-segment-active'));
    }
    guideAudio.addEventListener('ended', clearGuidePlaying);

    function playGuideSegment(url, absStart, absEnd, btn, cardEl) {
        if (!url || absEnd <= absStart) return;
        if (guidePlayingBtn === btn && !guideAudio.paused) { guideAudio.pause(); clearGuidePlaying(); return; }
        clearGuidePlaying();
        if (!elements.audioElement.paused) elements.audioElement.pause();
        guidePlayingBtn = btn;
        if (btn) {
            btn.classList.add('guide-seg-playing');
            const i = btn.querySelector('i');
            if (i) { btn.dataset.icon = i.className; i.className = 'fas fa-pause'; }
        }
        if (cardEl) cardEl.classList.add('guide-segment-active');
        const begin = () => {
            try { guideAudio.currentTime = absStart; } catch (e) {}
            guideAudioStopAt = absEnd;
            const p = guideAudio.play();
            if (p && p.catch) p.catch(() => {});
            if (guidePollTimer) clearInterval(guidePollTimer);
            guidePollTimer = setInterval(() => {
                if (guideAudioStopAt != null && guideAudio.currentTime >= guideAudioStopAt) {
                    guideAudio.pause();
                    clearGuidePlaying();
                }
            }, 120);
        };
        if (guideAudio.src !== url) {
            guideAudio.src = url;
            guideAudio.addEventListener('loadedmetadata', begin, { once: true });
            guideAudio.load();
        } else {
            begin();
        }
    }

    // Phrase list for a reciter — from the backend, or derived from `stops` as a fallback.
    function getGuidePhrases(det, lastW) {
        if (det.phrases && det.phrases.length) return det.phrases;
        const stops = (det.stops || []).slice().sort((a, b) => a.wpos - b.wpos);
        return stops.map((s, i) => ({
            first_wpos: i === 0 ? 0 : stops[i - 1].wpos + 1, last_wpos: s.wpos,
            start: i === 0 ? 0 : stops[i - 1].time, end: s.time,
        })).concat([{
            first_wpos: stops.length ? stops[stops.length - 1].wpos + 1 : 0, last_wpos: lastW,
            start: stops.length ? stops[stops.length - 1].time : 0, end: det.duration,
        }]);
    }

    // One row of segment-cards for a single reciter's phrases — the SAME
    // visual style the old positions.db-powered guide used, now sourced from
    // مُكْث's richer per-verse data.
    function buildSegmentRow(d, det, name, lastW, markByWpos, soloSet) {
        const phrases = getGuidePhrases(det, lastW);
        const row = document.createElement('div');
        row.className = 'guide-seg-row';
        row.dir = 'rtl';
        const seekable = det.audio_url && !isGuideYoutubeUrl(det.audio_url);

        let highWater = 0;
        phrases.forEach((ph, k) => {
            const isLast = k === phrases.length - 1;
            const first = ph.first_wpos, last = ph.last_wpos;
            const repeatedCount = Math.max(0, highWater - first);
            const isBackUp = repeatedCount > 0;
            highWater = Math.max(highWater, last + 1);
            const next = phrases[k + 1];
            const forwardStop = !isLast && next && next.first_wpos > last;

            const seg = document.createElement('div');
            seg.className = 'guide-segment' + (isLast ? ' guide-segment-last' : '') + (isBackUp ? ' guide-segment-repeat' : '');

            const num = document.createElement('span');
            num.className = 'guide-seg-num';
            num.textContent = guideToAr(k + 1);
            seg.appendChild(num);

            if (isBackUp) {
                const bdg = document.createElement('span');
                bdg.className = 'guide-seg-repeat-badge';
                bdg.innerHTML = '<i class="fas fa-rotate-left"></i> تكرار';
                bdg.title = `أعاد القارئ القراءة من «${d.words[first] || ''}»`;
                seg.appendChild(bdg);
            } else if (forwardStop && soloSet.has(last)) {
                const bdg = document.createElement('span');
                bdg.className = 'guide-seg-solo-badge';
                bdg.innerHTML = '<i class="fas fa-star"></i> انفرد بالوقف';
                bdg.title = 'انفرد القارئ بهذا الوقف بين القرّاء — لم يقف عنده غيره';
                seg.appendChild(bdg);
            }

            const wordsEl = document.createElement('div');
            wordsEl.className = 'guide-seg-words';
            wordsEl.dir = 'rtl';
            for (let wi = first; wi <= last; wi++) {
                if (wi > first) wordsEl.appendChild(document.createTextNode(' '));
                const ws = document.createElement('span');
                if (isBackUp && wi < first + repeatedCount) ws.className = 'guide-seg-repeated-word';
                ws.textContent = d.words[wi] || '';
                wordsEl.appendChild(ws);
            }
            seg.appendChild(wordsEl);

            if (seekable) {
                const play = document.createElement('button');
                play.type = 'button';
                play.className = 'guide-seg-play-btn';
                play.title = `استمع لمقطع ${name}`;
                play.innerHTML = '<i class="fas fa-play"></i>';
                play.addEventListener('click', (e) => { e.stopPropagation(); playGuideSegment(det.audio_url, det.verse_start + ph.start, det.verse_start + ph.end, play, seg); });
                seg.appendChild(play);
                seg.classList.add('guide-segment-seekable');
            }

            const foot = document.createElement('div');
            foot.className = 'guide-seg-waqf';
            const sym = markByWpos.get(last);
            if (isLast) {
                foot.innerHTML = '<span class="guide-waqf-sym guide-waqf-ras-aya">۝</span><span class="guide-waqf-lbl guide-waqf-ras-aya-lbl">رأس الآية</span>';
            } else if (sym) {
                foot.innerHTML = `<span class="guide-waqf-sym waqf-uthmanic">${guideWaqfGlyph(sym)}</span><span class="guide-waqf-lbl">${guideSymName(sym)}</span>`;
            } else {
                foot.innerHTML = `<span class="guide-waqf-lbl">${isBackUp ? 'موضع الإعادة' : 'وقف'}</span>`;
            }
            const time = document.createElement('span');
            time.className = 'guide-seg-time';
            time.textContent = '~' + guideToAr((ph.end - ph.start).toFixed(1)) + 'ث';
            foot.appendChild(time);
            seg.appendChild(foot);

            if (!isLast) {
                const arrow = document.createElement('span');
                arrow.className = 'guide-seg-arrow';
                arrow.innerHTML = '<i class="fas fa-arrow-left"></i>';
                seg.appendChild(arrow);
            }
            row.appendChild(seg);
        });
        return row;
    }

    // What did this reciter pause at that NO other reciter did (انفرد), and does
    // a printed mushaf prescribe a waqf there?
    function buildGuideSoloBlock(det) {
        const block = document.createElement('div');
        block.className = 'guide-solo-detail';
        const items = (det && det.solo_stops_detail) || [];
        if (!items.length) return block;
        const head = document.createElement('div');
        head.className = 'guide-solo-head';
        head.innerHTML = `<i class="fas fa-user-tag"></i> انفرد بالوقف <span class="guide-solo-count">${guideToAr(items.length)}</span>`;
        block.appendChild(head);
        const list = document.createElement('div');
        list.className = 'guide-solo-items';
        items.forEach(it => {
            const el = document.createElement('div');
            el.className = 'guide-solo-item' + (it.mushaf_matches && it.mushaf_matches.length ? ' guide-solo-item-matched' : '');
            let html = `<span class="guide-solo-word">${it.word || 'موضع'}</span>`
                     + `<span class="guide-solo-time">${guideToAr((it.time || 0).toFixed(1))}ث</span>`;
            if (it.mushaf_matches && it.mushaf_matches.length) {
                html += it.mushaf_matches.map(m =>
                    `<span class="guide-mushaf-match" title="يوافق علامة وقف مطبوعة في مصحف ${m.mushaf}">يوافق ${m.mushaf} <b>${m.symbol}</b></span>`
                ).join('');
            } else {
                html += `<span class="guide-solo-nomatch" title="لا توجد علامة وقف مطبوعة عند هذا الموضع في المصاحف المتوفرة">بلا علامة مطبوعة</span>`;
            }
            el.innerHTML = html;
            list.appendChild(el);
        });
        block.appendChild(list);
        return block;
    }

    // كيف قرأها كل قارئ — reciters who pause/back up at the same word positions
    // are grouped into one row of cards instead of repeating per reciter.
    function buildGuideReciters(d, lastW, markByWpos, soloSet) {
        if (!d.reciters || !d.reciters.length) return null;
        const mushafPos = new Set((d.mushafs || []).flatMap(m => m.marks.map(mk => mk.wpos)));
        const nameById = new Map(d.reciters.map(r => [r.id, r.name_ar]));

        const groups = [];
        const bySig = new Map();
        d.reciters.forEach(r => {
            const det = d.per_reciter[r.id];
            const sig = getGuidePhrases(det, lastW).map(p => `${p.first_wpos}-${p.last_wpos}`).join(',');
            let g = bySig.get(sig);
            if (!g) { g = { members: [] }; bySig.set(sig, g); groups.push(g); }
            g.members.push(r.id);
        });
        groups.sort((a, b) => b.members.length - a.members.length);

        const wrap = document.createElement('div');
        wrap.innerHTML = '<div class="guide-section-title"><i class="fas fa-users"></i> كيف قرأها كل قارئ</div>'
            + '<p class="guide-reciters-note"><i class="fas fa-circle-info"></i> تختلف الأزمنة بين القرّاء تبعًا لأدائهم (قصر المدّ المنفصل يجعل القراءة أسرع)؛ الزمن المعروض هو مدّة كل مقطع.</p>';
        const list = document.createElement('div');
        list.className = 'guide-reciters-list';
        wrap.appendChild(list);

        groups.forEach(group => {
            const card = document.createElement('div');
            card.className = 'guide-reciter-card';

            const det0 = d.per_reciter[group.members[0]];
            const nStops = det0.stops.length;
            const onMushaf = (det0.stops || []).filter(s => mushafPos.has(s.wpos)).length;
            const nReps = det0.repeats.length;
            const durations = group.members.map(id => d.per_reciter[id].duration);
            const minD = Math.round(Math.min(...durations)), maxD = Math.round(Math.max(...durations));
            const durText = minD === maxD ? `~${guideToAr(minD)}ث` : `~${guideToAr(minD)}–${guideToAr(maxD)}ث`;

            const head = document.createElement('div');
            head.className = 'guide-reciter-head';
            let activeId = group.members[0];
            let row, soloBlock;

            const qasrEl = document.createElement('span');
            qasrEl.className = 'guide-qasr-badge';
            qasrEl.innerHTML = '<i class="fas fa-gauge-high"></i> قصر المنفصل';
            qasrEl.title = 'يقرأ بقصر المدّ المنفصل (حركتان)، فتكون قراءته أسرع من قارئ الإشباع';
            const syncQasr = () => { qasrEl.hidden = !(d.per_reciter[activeId] || {}).qasr_munfasil; };

            if (group.members.length === 1) {
                const nameEl = document.createElement('span');
                nameEl.className = 'guide-reciter-name';
                nameEl.textContent = nameById.get(activeId);
                head.appendChild(nameEl);
            } else {
                const namesWrap = document.createElement('div');
                namesWrap.className = 'guide-reciter-names';
                group.members.forEach(id => {
                    const chip = document.createElement('button');
                    chip.type = 'button';
                    chip.className = 'guide-reciter-chip' + (id === activeId ? ' guide-reciter-chip-active' : '');
                    chip.textContent = nameById.get(id);
                    chip.title = 'استمع بصوت ' + nameById.get(id);
                    chip.addEventListener('click', () => {
                        if (id === activeId) return;
                        activeId = id;
                        namesWrap.querySelectorAll('.guide-reciter-chip').forEach(c => c.classList.toggle('guide-reciter-chip-active', c === chip));
                        const newRow = buildSegmentRow(d, d.per_reciter[activeId], nameById.get(activeId), lastW, markByWpos, soloSet);
                        row.replaceWith(newRow);
                        row = newRow;
                        const newSolo = buildGuideSoloBlock(d.per_reciter[activeId]);
                        soloBlock.replaceWith(newSolo);
                        soloBlock = newSolo;
                        syncQasr();
                    });
                    namesWrap.appendChild(chip);
                });
                head.appendChild(namesWrap);
            }
            head.appendChild(qasrEl);
            syncQasr();

            const stats = document.createElement('span');
            stats.className = 'guide-reciter-stats';
            stats.innerHTML = `<span><b>${guideToAr(nStops)}</b> ${nStops === 1 ? 'وقفة' : 'وقفات'}</span>`
                + (mushafPos.size ? `<span class="guide-adhere" title="عدد وقفاته الواقعة على موضع وقف في أحد المصاحف"><i class="fas fa-book-quran"></i> موافقة المصحف <b>${guideToAr(onMushaf)}/${guideToAr(nStops)}</b></span>` : '')
                + (nReps ? `<span><b>${guideToAr(nReps)}</b> ${nReps === 1 ? 'إعادة' : 'إعادات'}</span>` : '')
                + `<span>${durText}</span>`
                + (group.members.length > 1 ? `<span class="guide-reciter-count" title="عدد القرّاء الذين قرؤوا الآية بنفس مواضع الوقف"><i class="fas fa-users"></i> ${guideToAr(group.members.length)}/${guideToAr(d.reciters_total)}</span>` : '');
            head.appendChild(stats);

            card.appendChild(head);
            soloBlock = buildGuideSoloBlock(d.per_reciter[activeId]);
            card.appendChild(soloBlock);
            row = buildSegmentRow(d, d.per_reciter[activeId], nameById.get(activeId), lastW, markByWpos, soloSet);
            card.appendChild(row);
            list.appendChild(card);
        });
        return wrap;
    }

    async function fetchAndBuildRecitationGuide() {
        const surah = elements.surahSelect.value;
        const ayah = elements.ayahSelect.value;
        if (!surah || !ayah) return;

        const guideContainer = document.getElementById('recitation-guide-container');
        guideContainer.innerHTML = '<div class="guide-loading"><i class="fas fa-spinner fa-spin"></i> جاري تحميل بيانات الوقف…</div>';
        clearGuidePlaying();

        try {
            const d = await fetchData(`/api/waqf/${surah}/${ayah}`);
            guideContainer.innerHTML = '';

            if (!d.reciters || !d.reciters.length || !d.words || !d.words.length) {
                guideContainer.innerHTML =
                    '<div class="guide-no-waqf">' +
                    '<span class="guide-no-waqf-sym">۝</span>' +
                    '<span class="guide-no-waqf-title">لا توجد بيانات وقف لهذه الآية بعد</span>' +
                    '<span class="guide-no-waqf-body">لا تتوفر تسجيلات محاذاة لهذه الآية حتى الآن.</span>' +
                    '</div>';
                return;
            }

            const reciter = elements.reciterSelect.value;
            const lastW = d.words.length - 1;
            const markByWpos = new Map();
            ['المدينة الجديد', 'المدينة القديم', 'الشمرلي', 'الأزهر', 'قطر', 'الكويت'].forEach((id) => {
                const m = (d.mushafs || []).find((x) => x.id === id);
                if (m) m.marks.forEach((mk) => { if (!markByWpos.has(mk.wpos)) markByWpos.set(mk.wpos, mk.symbol); });
            });
            const soloSet = new Set((d.union_stops || []).filter((u) => u.solo).map((u) => u.wpos));

            // 1) The currently-selected reciter's own segment row — same visual
            // language as the old per-reciter guide, sourced from مُكْث's data.
            const currentDet = d.per_reciter[reciter];
            if (currentDet) {
                const wrapper = document.createElement('div');
                wrapper.className = 'recitation-guide';
                const titleEl = document.createElement('div');
                titleEl.className = 'guide-title';
                titleEl.innerHTML = `<i class="fas fa-route"></i> دليل التلاوة — ${currentDet.name_ar || reciter}`;
                wrapper.appendChild(titleEl);
                const subtitleEl = document.createElement('p');
                subtitleEl.className = 'guide-subtitle';
                subtitleEl.textContent = 'الآية مقسّمة إلى مقاطع وفق مواضع وقف هذا القارئ. اقرأ كل مقطع حتى الرمز ثم قف أو استمر حسب الحكم.';
                wrapper.appendChild(subtitleEl);
                wrapper.appendChild(buildSegmentRow(d, currentDet, currentDet.name_ar || reciter, lastW, markByWpos, soloSet));
                const soloBlock = buildGuideSoloBlock(currentDet);
                if (soloBlock.childElementCount) wrapper.appendChild(soloBlock);
                guideContainer.appendChild(wrapper);
            } else {
                guideContainer.innerHTML +=
                    '<div class="guide-no-waqf">' +
                    '<span class="guide-no-waqf-sym">🎙</span>' +
                    '<span class="guide-no-waqf-title">دليل التلاوة غير متاح لهذا القارئ</span>' +
                    '<span class="guide-no-waqf-body">لا توجد بيانات تسجيل لهذا القارئ في هذه الآية بعد.</span>' +
                    '</div>';
            }

            // مقارنة القرّاء بمصاحف الوقف (the comparison matrix) stays exclusive
            // to مُكْث's /waqf page — the main page only gets the per-reciter
            // segment row above and the reciters-comparison section below.

            // كيف قرأها كل قارئ
            const recitersWrap = buildGuideReciters(d, lastW, markByWpos, soloSet);
            if (recitersWrap) guideContainer.appendChild(recitersWrap);
        } catch (error) {
            guideContainer.innerHTML = '<div class="guide-error"><i class="fas fa-triangle-exclamation"></i> خطأ في تحميل دليل التلاوة</div>';
            console.error('Recitation guide error:', error);
        }
    }

    function renderReaderWord(wordElement, word, index, wordIndexToSegmentMap) {
        const isIndoPak = document.body.dataset.fontType === 'indopak';
        // IndoPak: marks always live in .waqf-stack; never leave ruling glyphs
        // in .word-base (stripEmbeddedWaqf only covers Madinah ۖ–ۜ).
        const cleanText = isIndoPak
            ? String(word || '').replace(INDOPAK_INLINE_WAQF_STRIP, '')
            : stripEmbeddedWaqf(word);
        wordElement.dataset.textOriginal = word;
        wordElement.dataset.textClean = cleanText;
        const mode = getCurrentWaqfMode();
        const wordContent = document.createElement('span');
        wordContent.className = 'word-content';
        const wordBase = document.createElement('span');
        wordBase.className = 'word-base';
        const visibleText = (isIndoPak || mode === 'selected' || mode === 'none') ? cleanText : word;
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
        // Mutually exclusive with the عرض غريب الكلمات list: once that's open it
        // already shows every word's meaning, so a hover tooltip on top would
        // just duplicate the same text right next to it.
        if (elements.wordMeaningVisible) return;
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
        } else {
            // Last ayah of the surah — roll into the next surah's first ayah
            // rather than silently doing nothing (the button gave no other
            // sign it had hit a boundary).
            const currentSurahIndex = elements.surahSelect.selectedIndex;
            if (currentSurahIndex < elements.surahSelect.options.length - 1) {
                elements.surahSelect.selectedIndex = currentSurahIndex + 1;
                currentRepeatCount = 0;
                await loadAyahs(); // repopulates ayah-select, lands on ayah 1, loads + plays it
                elements.audioElement.play();
                updatePlayPauseButton();
            }
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
        } else {
            // First ayah of the surah — roll back into the previous surah's
            // last ayah, mirroring loadNextAyah()'s forward rollover.
            const currentSurahIndex = elements.surahSelect.selectedIndex;
            if (currentSurahIndex > 0) {
                elements.surahSelect.selectedIndex = currentSurahIndex - 1;
                currentRepeatCount = 0;
                await loadAyahs(); // repopulates ayah-select for the previous surah, defaults to ayah 1
                elements.ayahSelect.selectedIndex = elements.ayahSelect.options.length - 1; // ...move to its last ayah
                await loadQuranData();
                elements.audioElement.play();
                updatePlayPauseButton();
            }
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

    // With one shared per-surah audio file, 'ended' only fires at the surah's
    // very end — not per ayah — so ayah/range boundaries are watched via
    // 'timeupdate' against ayahStopAt instead (set by loadQuranData() for a
    // single ayah, or scheduleRangeStop() while a range is playing).
    // 200ms grace period after (re)arming: seeking currentTime back to an
    // ayah's start doesn't apply instantly, so the very next 'timeupdate'
    // tick can still report the pre-seek currentTime — without this guard
    // that stale tick immediately re-triggers the boundary we just reset,
    // firing the repeat callback multiple times per real loop (confirmed
    // live: currentRepeatCount was observed oscillating instead of
    // monotonically increasing before this guard was added).
    const AYAH_BOUNDARY_GRACE_MS = 200;
    elements.audioElement.addEventListener('timeupdate', () => {
        if (ayahStopAt !== null
            && Date.now() - ayahStopAtArmedAt > AYAH_BOUNDARY_GRACE_MS
            && elements.audioElement.currentTime >= ayahStopAt) {
            const cb = ayahBoundaryCallback;
            clearAyahStopAt();
            if (cb) cb();
        }
    });

    // Non-range single-ayah repeat: fires when the current ayah's own end
    // boundary is crossed (see loadQuranData()).
    function handleAyahEndedNormal() {
        elements.audioElement.pause(); // stop before it drifts into the next ayah's audio
        currentRepeatCount++;
        const ayahNumber = parseInt(elements.ayahSelect.value, 10);
        const verse = currentSurahAudio && currentSurahAudio.verses.get(ayahNumber);
        if (currentRepeatCount < maxRepeats && verse) {
            elements.audioElement.currentTime = verse.start;
            setAyahStopAt(verse.end, handleAyahEndedNormal);
            elements.audioElement.play().then(updatePlayPauseButton).catch(() => {});
        } else {
            currentRepeatCount = 0;
            // Keep the boundary armed at this same ayah's end (rather than
            // clearing it) so a plain "play" click — not a fresh
            // loadQuranData() navigation — still stops here instead of
            // drifting into the next ayah's audio.
            if (verse) setAyahStopAt(verse.end, handleAyahEndedNormal);
            updatePlayPauseButton();
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
        if (startAyahIndex > endAyahIndex) return;

        isRangeMode = true;
        currentRepeatCount = 0;
        clearAyahStopAt(); // drop any stale boundary from prior single-ayah playback
        elements.ayahSelect.selectedIndex = startAyahIndex;
        await loadQuranData();
        scheduleRangeStop(startAyahIndex, endAyahIndex);
        elements.audioElement.play();
        updatePlayPauseButton();
        closeModal();

        if (elements.playPauseButton.rangePlayPauseHandler) {
            elements.playPauseButton.removeEventListener('click', elements.playPauseButton.rangePlayPauseHandler);
        }
        // Remove the original play/pause event listener to prevent conflicts
        elements.playPauseButton.removeEventListener('click', togglePlayPause);

        const onPlayPause = () => {
            if (elements.audioElement.paused) {
                elements.audioElement.play();
            } else {
                elements.audioElement.pause();
            }
            updatePlayPauseButton();
        };
        elements.playPauseButton.rangePlayPauseHandler = onPlayPause;
        elements.playPauseButton.addEventListener('click', onPlayPause);
    }

    // Sets ayahStopAt/ayahBoundaryCallback for the CURRENTLY-selected ayah
    // while a range is playing — on boundary, advances to the next ayah in
    // the range, loops the whole range, or finishes. Re-called after every
    // step since loadQuranData() (isRangeMode=true) doesn't set these itself.
    function scheduleRangeStop(startAyahIndex, endAyahIndex) {
        const ayahNumber = parseInt(elements.ayahSelect.value, 10);
        const verse = currentSurahAudio && currentSurahAudio.verses.get(ayahNumber);
        if (!verse) { clearAyahStopAt(); return; }
        setAyahStopAt(verse.end, async () => {
            elements.audioElement.pause();
            if (elements.ayahSelect.selectedIndex < endAyahIndex) {
                // More verses left in this loop — advance to next
                elements.ayahSelect.selectedIndex++;
                await loadQuranData();
                scheduleRangeStop(startAyahIndex, endAyahIndex);
                elements.audioElement.play();
                updatePlayPauseButton();
            } else {
                // Reached end of range — check if we should loop the whole range again
                currentRepeatCount++;
                if (currentRepeatCount < maxRepeats) {
                    elements.ayahSelect.selectedIndex = startAyahIndex;
                    await loadQuranData();
                    scheduleRangeStop(startAyahIndex, endAyahIndex);
                    elements.audioElement.play();
                    updatePlayPauseButton();
                } else {
                    cleanupRangeMode();
                    updatePlayPauseButton();
                }
            }
        });
    }

    function cleanupRangeMode() {
        isRangeMode = false;
        currentRepeatCount = 0;
        clearAyahStopAt();
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
            return await window.AtharApi.json(url);
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
        } else {
            elements.audioElement.pause();
        }
        // Icon/label update happens via the audioElement 'play'/'pause'
        // listeners (see addEventListeners()) — not here, so it stays
        // correct even when play()/pause() resolves asynchronously.
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

    const _ARABIC_DIGITS = '٠١٢٣٤٥٦٧٨٩';
    function formatAudioTime(seconds) {
        if (!isFinite(seconds) || seconds < 0) seconds = 0;
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        const toArabicDigits = (str) => String(str).replace(/[0-9]/g, (d) => _ARABIC_DIGITS[d]);
        return `${toArabicDigits(m)}:${toArabicDigits(String(s).padStart(2, '0'))}`;
    }

    function updateAudioSeekUI() {
        const audio = elements.audioElement;
        if (!audio || !elements.audioSeekSlider) return;
        const duration = audio.duration;
        if (isFinite(duration) && duration > 0) {
            if (!isScrubbingAudio) {
                elements.audioSeekSlider.value = String(Math.round((audio.currentTime / duration) * 1000));
            }
            if (elements.audioDurationLabel) elements.audioDurationLabel.textContent = formatAudioTime(duration);
        }
        if (!isScrubbingAudio && elements.audioCurrentTimeLabel) {
            elements.audioCurrentTimeLabel.textContent = formatAudioTime(audio.currentTime);
        }
    }

    function resetAudioSeekUI() {
        isScrubbingAudio = false;
        if (elements.audioSeekSlider) elements.audioSeekSlider.value = '0';
        if (elements.audioCurrentTimeLabel) elements.audioCurrentTimeLabel.textContent = formatAudioTime(0);
        if (elements.audioDurationLabel) elements.audioDurationLabel.textContent = formatAudioTime(0);
    }

    function updateAudioMuteButton() {
        if (!elements.audioMuteButton || !elements.audioElement) return;
        const icon = elements.audioMuteButton.querySelector('i');
        if (!icon) return;
        icon.classList.remove('fa-volume-up', 'fa-volume-mute');
        icon.classList.add(elements.audioElement.muted ? 'fa-volume-mute' : 'fa-volume-up');
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
});
