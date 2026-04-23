document.addEventListener('DOMContentLoaded', async () => {
    const elements = getElements();
    const reciterAudioDataMap = {};
    let quranTextData;
    let currentSegments = [];
    let currentAyahData = null; // Cache for current ayah data
    let currentRepeatCount = 0; // Track current repeat count
    let maxRepeats = 1; // Track maximum repeats set by user
    const fontCache = {};
    const loadedShamarlyFonts = new Set();

    // Load user preferences from localStorage
    loadUserPreferences();
    
    addEventListeners();

    // ── Per-mushaf color classes ─────────────────────────────────────────────
    // MUST be declared before the first `await` so the const is initialized
    // when loadMushafVersions() → getMushafColorClass() runs.
    const MUSHAF_COLOR_MAP = [
        { match: /المدينة|مدينة/,  cls: 'waqf-mushaf-madinah'  },
        { match: /الشمرلي|شمرلي/,  cls: 'waqf-mushaf-shamarly' },
        { match: /الأزهر|أزهر/,    cls: 'waqf-mushaf-azhar'    },
        { match: /ورش/,            cls: 'waqf-mushaf-warsh'    },
        { match: /الحصري|حصري/,    cls: 'waqf-mushaf-husary'   },
    ];

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
        
        // Load reciter preference
        const savedReciter = localStorage.getItem('quranApp_reciter');
        if (savedReciter && elements.reciterSelect) {
            elements.reciterSelect.value = savedReciter;
        }
        
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
                        btn.classList.toggle('active');
                        localStorage.setItem('quranApp_mushafVersions',
                            JSON.stringify(getSelectedMushafVersions()));
                        loadQuranData();
                    });
                    dropdown.appendChild(btn);
                });
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
            closeBookmarksModal: document.querySelector('.close-bookmarks')
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
        window.addEventListener('click', (event) => {
            if (event.target === elements.modal) closeModal();
        });
        elements.quranTextSelect.addEventListener('change', async () => {
            // Add loading indicator
            const originalText = elements.quranTextContainer.innerHTML;
            elements.quranTextContainer.innerHTML = '<div class="loading">جاري تحميل الخط الجديد...</div>';
            
            try {
                changeFont(elements.quranTextSelect.value);
                await loadQuranTextData();
                await updateDisplayedText();
            } catch (error) {
                console.error('Error changing font:', error);
                elements.quranTextContainer.innerHTML = originalText;
                handleError('Error changing font:', error, elements.quranTextContainer, 'خطأ في تغيير الخط. يرجى المحاولة مرة أخرى.');
            }
        });
        elements.playPauseButton.addEventListener('click', togglePlayPause);

        document.getElementById('show-transliteration').addEventListener('click', toggleTransliteration);
        document.getElementById('show-tafseer').addEventListener('click', toggleTafseer);
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
        await loadQuranData();
        updatePlayPauseButton();
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
        updateGlobalAyahToVerseKey();
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
                        preloadedAudio.src = `/api/audio-proxy?url=${encodeURIComponent(data.reciters[reciter].audio_url)}`;
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
            const query = params.toString() ? '?' + params.toString() : '';
            currentAyahData = await fetchData(`/api/surahs/${surahNumber}/ayahs/${ayahNumber}${query}`);
            const verseKey = `${surahNumber}:${ayahNumber}`;
            const globalAyahNumber = currentAyahData.id;
            if (!globalAyahNumber) throw new Error(`No global Ayah number found for Surah ${surahNumber}, Ayah ${ayahNumber}`);
    
            const reciter = elements.reciterSelect.value;
            const reciterAudio = currentAyahData.reciters[reciter];
            if (!reciterAudio) throw new Error('Reciter audio not found');
    
            // Use already cached quranTextData instead of making redundant API call
            const ayahText = quranTextData?.[verseKey]?.text || currentAyahData.text;
    
            elements.audioElement.src = `/api/audio-proxy?url=${encodeURIComponent(reciterAudio.audio_url)}`;
            currentSegments = reciterAudio.segments;
            displayQuranicText(ayahText, currentSegments, currentAyahData.waqf_symbols || []);
            displayTransliteration(currentAyahData.transliteration);
            await maybeRefreshTafseer(surahNumber, ayahNumber);
            // Only display word meanings if they should be visible
            if (elements.wordMeaningVisible) {
                displayWordMeanings(currentAyahData.word_meanings || {}, ayahText);
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
        const params = new URLSearchParams();
        versions.forEach((v) => params.append('mushaf_version', v));
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

        if (readingView === 'page') {
            renderShamarlyPage(shamarlyPayload);
        } else if (readingView === 'verse-mushaf-lines') {
            renderShamarlyVerseLines(shamarlyPayload);
        } else {
            renderShamarlyVerseWords(shamarlyPayload, reciterAudio.segments || []);
        }

        elements.audioElement.src = `/api/audio-proxy?url=${encodeURIComponent(reciterAudio.audio_url)}`;
        currentSegments = reciterAudio.segments || [];
        displayTransliteration(currentAyahData.transliteration);
        await maybeRefreshTafseer(surahNumber, ayahNumber);
        if (elements.wordMeaningVisible) {
            const verseText = shamarlyPayload?.raw_text || currentAyahData.text || '';
            displayWordMeanings(currentAyahData.word_meanings || {}, verseText);
        } else {
            elements.wordMeaningContainer.innerHTML = '';
        }

        updatePlayPauseButton();
        saveUserPreferences();
        preloadNextAyah();
        elements.audioElement.onended = updatePlayPauseButton;
    }

    async function ensureShamarlyFontLoaded(fontName) {
        if (!fontName || loadedShamarlyFonts.has(fontName)) {
            return;
        }
        try {
            const font = new FontFace(fontName, `url('/static/${fontName}.ttf') format('truetype')`);
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
                const query = _p.toString() ? '?' + _p.toString() : '';
                currentAyahData = await fetchData(`/api/surahs/${surahNumber}/ayahs/${ayahNumber}${query}`);
            }
            
            const verseKey = `${surahNumber}:${ayahNumber}`;
            // Use already cached quranTextData instead of making redundant API call
            const ayahText = quranTextData?.[verseKey]?.text || currentAyahData.text;
            displayQuranicText(ayahText, currentSegments, currentAyahData.waqf_symbols || []);
            displayTransliteration(currentAyahData.transliteration);
            await maybeRefreshTafseer(surahNumber, ayahNumber);
            if (elements.wordMeaningVisible) {
                displayWordMeanings(currentAyahData.word_meanings || {}, ayahText);
            } else {
                elements.wordMeaningContainer.innerHTML = '';
            }
        } catch (error) {
            handleError('Error updating Quran text:', error, elements.quranTextContainer, 'خطأ في تحديث النص. يرجى المحاولة مرة أخرى لاحقًا.');
        }
    }

    function displayQuranicText(text, segments, waqfSymbols = []) {
        elements.quranTextContainer.style.fontFamily = '';
        elements.quranTextContainer.innerHTML = '';
        const words = text.split(' ');
        const wordIndexToSegmentMap = new Map();
        const waqfByToken = buildWaqfByTokenIndex(waqfSymbols, words);
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
    }

    function renderShamarlyVerseWords(shamarlyPayload, segments) {
        const words = Array.isArray(shamarlyPayload?.words) ? shamarlyPayload.words : [];
        const waqfByToken = buildWaqfByTokenIndex(shamarlyPayload?.waqf_symbols, words);
        const wordIndexToSegmentMap = new Map();
        const wordElements = [];
        mapSegmentsToWords(segments, wordIndexToSegmentMap);

        elements.quranTextContainer.innerHTML = '';

        words.forEach((word, index) => {
            const wordElement = createWordElement(word?.text || '', index, wordIndexToSegmentMap);
            const waqfSymbols = waqfByToken.get(index);
            if (waqfSymbols) {
                appendWaqfEntries(wordElement, waqfSymbols, shamarlyPayload?.mushaf_version || '');
            }
            wordElements[index] = wordElement;
            elements.quranTextContainer.appendChild(wordElement);
            elements.quranTextContainer.appendChild(document.createTextNode(' '));
        });

        attachHighlightHandler(wordElements, wordIndexToSegmentMap);
    }

    function renderShamarlyVerseLines(shamarlyPayload) {
        const lines = Array.isArray(shamarlyPayload?.verse_lines) ? shamarlyPayload.verse_lines : [];
        const waqfByToken = buildWaqfByTokenIndex(shamarlyPayload?.waqf_symbols, shamarlyPayload?.words || []);
        const verseWords = Array.isArray(shamarlyPayload?.words) ? shamarlyPayload.words : [];
        const coveredTokenIndexes = new Set();

        elements.quranTextContainer.innerHTML = '';
        lines.forEach((line) => {
            const lineEl = document.createElement('div');
            lineEl.className = 'shamarly-line';
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
                    'ر': 'ۗ',
                    'ۘ': 'ۘ',
                    'ۗ': 'ۗ',
                    'ۖ': 'ۖ',
                    'ۚ': 'ۚ',
                    'ۙ': 'ۙ',
                    'ۛ': 'ۛ',
                    'ۜ': 'ۜ',   // Warsh stop sign — pass through
                };
                return waqfGlyphMap[token] || token;
            })
            .join('');
    }

    // Normalise Warsh waqf raw DB values to the Warsh Unicode stop sign ۜ (U+06DC)
    function normalizeWarshWaqfText(raw) {
        if (!raw || !raw.trim()) return '';
        // If the raw value already is the Warsh glyph, keep it
        if (raw.trim() === '\u06DC') return '\u06DC';
        // Any non-empty Warsh waqf indicator = stop → ۜ
        return '\u06DC';
    }

    // ── Waqf symbol meanings (display only, no color here) ─────────────────
    const WAQF_INFO = {
        'م':   { meaning: 'وقف لازم — الوقف واجب'                                              },
        'قلى': { meaning: 'قلى — الأفضل الوقف'                                                 },
        'قلي': { meaning: 'قلى — الأفضل الوقف'                                                 },
        'ق':   { meaning: 'قلى — الأفضل الوقف'                                                 },
        'ر':   { meaning: 'راجح — الأفضل الوقف'                                                },
        'ص':   { meaning: 'صلى — الأفضل الوصل'                                                 },
        'صلى': { meaning: 'صلى — الأفضل الوصل'                                                 },
        'صلي': { meaning: 'صلى — الأفضل الوصل'                                                 },
        'ج':   { meaning: 'جائز — يجوز الوقف والوصل'                                           },
        'لا':  { meaning: 'لا وقف — يجب الوصل'                                                 },
        'ع':   { meaning: 'معانقة — إذا وقفت على أحدهما لا تقف على الآخر'                     },
        '↺':   { meaning: 'وقف إعادة — ارجع للبداية'                                           },
        '▶':   { meaning: 'بداية الإعادة'                                                       },
        '\u06DC': { meaning: 'توقف — علامة وقف مصحف ورش'                                    },
    };

    function getWaqfInfo(rawSymbol) {
        const key = (rawSymbol || '').trim();
        return WAQF_INFO[key] || { meaning: key };
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
            // No normalization — display the raw DB value as-is
            return { text: raw, extraClass: 'waqf-warsh', title: raw };
        }

        const normalized = normalizeNonWarshWaqfText(raw);
        const isHusaryRepeat = normalized.includes('\u21BA') || normalized.includes('\u25B6');
        return {
            text: normalized,
            extraClass: isHusaryRepeat ? 'waqf-latin' : '',
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
        const symbolSpan = document.createElement('span');

        // Color is always per-mushaf; add waqf-latin only for font
        const isLatin = /[\u21BA\u25B6]/.test(displayData.text);
        const colorClass = getMushafColorClass(mushafVersionOverride);
        symbolSpan.className = 'waqf-symbol ' + colorClass + (isLatin ? ' waqf-latin' : '');
        if (mushafVersionOverride) symbolSpan.dataset.version = mushafVersionOverride;
        symbolSpan.textContent = displayData.text;

        // Tooltip: "مصحف: الأزهر | ج — جائز"
        const info = getWaqfInfo(displayData.title.trim());
        const versionLabel = mushafVersionOverride ? `مصحف: ${mushafVersionOverride}` : '';
        const symbolLabel = info.meaning || displayData.title.trim();
        symbolSpan.title = [versionLabel, symbolLabel].filter(Boolean).join(' | ');

        stack.appendChild(symbolSpan);
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

        // Enable mushaf-version dropdown only when overlay waqf is visible
        const toggleBtn = document.getElementById('mushaf-version-toggle');
        if (toggleBtn) {
            toggleBtn.disabled = (mode === 'original' || mode === 'none');
        }

        // Swap embedded waqf text in already-rendered word elements
        const showEmbedded = mode === 'both' || mode === 'original';
        document.querySelectorAll('.word-token[data-text-original]').forEach((el) => {
            const newText = showEmbedded ? (el.dataset.textOriginal || '') : (el.dataset.textClean || '');
            // Find the leading text node (before any .waqf-symbol child span)
            let textNode = null;
            for (const child of el.childNodes) {
                if (child.nodeType === Node.TEXT_NODE) {
                    textNode = child;
                    break;
                }
            }
            if (textNode) {
                textNode.nodeValue = newText;
            } else {
                el.insertBefore(document.createTextNode(newText), el.firstChild);
            }
        });
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

    function displayWordMeanings(wordMeanings, verseText) {
        if (elements.wordMeaningContainer) {
            elements.wordMeaningContainer.innerHTML = '';
            const entries = Object.entries(wordMeanings);
            if (entries.length > 0 && verseText) {
                const list = document.createElement('ul');
                // Split verse text into words and clean them for matching
                const verseWords = verseText.split(' ').filter(word => word.trim() !== '');
                
                // Build Maps for O(1) lookups instead of O(n) array searches
                const exactMap = new Map(entries.map(([w, m]) => [w, m]));
                const usedWords = new Set();
                
                // Create ordered list based on verse word sequence
                verseWords.forEach(verseWord => {
                    // Clean the verse word by removing diacritics and numbers for better matching
                    const cleanVerseWord = verseWord.replace(/[٠-٩0-9]/g, '').trim();
                    
                    // Try exact match first using Map (O(1))
                    let matchWord = null;
                    let matchMeaning = null;
                    
                    if (exactMap.has(cleanVerseWord) && !usedWords.has(cleanVerseWord)) {
                        matchWord = cleanVerseWord;
                        matchMeaning = exactMap.get(cleanVerseWord);
                    } else if (exactMap.has(verseWord) && !usedWords.has(verseWord)) {
                        matchWord = verseWord;
                        matchMeaning = exactMap.get(verseWord);
                    }
                    
                    // If exact match not found, try partial matching (fallback)
                    if (!matchWord) {
                        for (const [word, meaning] of exactMap) {
                            if (usedWords.has(word)) continue;
                            if (word.includes(cleanVerseWord) || cleanVerseWord.includes(word)) {
                                matchWord = word;
                                matchMeaning = meaning;
                                break;
                            }
                        }
                    }
                    
                    if (matchWord && !usedWords.has(matchWord)) {
                        usedWords.add(matchWord);
                        const listItem = document.createElement('li');
                        listItem.textContent = `${matchWord}: ${matchMeaning}`;
                        list.appendChild(listItem);
                    }
                });
                
                // Add any remaining meanings that weren't matched
                for (const [word, meaning] of exactMap) {
                    if (!usedWords.has(word)) {
                        const listItem = document.createElement('li');
                        listItem.textContent = `${word}: ${meaning}`;
                        list.appendChild(listItem);
                    }
                }
                
                elements.wordMeaningContainer.appendChild(list);
            } else if (entries.length > 0) {
                // Fallback to original behavior if no verse text provided
                const list = document.createElement('ul');
                entries.forEach(([word, meaning]) => {
                    const listItem = document.createElement('li');
                    listItem.textContent = `${word}: ${meaning}`;
                    list.appendChild(listItem);
                });
                elements.wordMeaningContainer.appendChild(list);
            } else {
                elements.wordMeaningContainer.innerHTML = 'لا يوجد معاني متاحة';
            }
        }
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

    async function maybeRefreshTafseer(surahNumber, ayahNumber) {
        const tafseerContainer = document.getElementById('tafseer-container');
        if (tafseerContainer && tafseerContainer.style.display !== 'none') {
            await fetchAndDisplayTafseer(surahNumber, ayahNumber);
        } else {
            displayTafseers({});
        }
    }

    function toggleWordMeaning() {
        elements.wordMeaningVisible = !elements.wordMeaningVisible;
        if (elements.wordMeaningVisible) {
            elements.wordMeaningContainer.style.display = 'block';
            // Refresh word meanings for the current verse when toggling to visible
            if (currentAyahData) {
                const verseKey = `${elements.surahSelect.value}:${elements.ayahSelect.value}`;
                const ayahText = quranTextData?.[verseKey]?.text || currentAyahData.text;
                displayWordMeanings(currentAyahData.word_meanings || {}, ayahText);
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
        }
    }

    async function fetchAndBuildRecitationGuide() {
        const surah = elements.surahSelect.value;
        const ayah = elements.ayahSelect.value;
        if (!surah || !ayah) return;

        const guideContainer = document.getElementById('recitation-guide-container');
        guideContainer.innerHTML = '<div class="guide-loading"><i class="fas fa-spinner fa-spin"></i> جاري تحميل بيانات الوقف…</div>';

        try {
            // Use the currently selected mushaf versions; fall back to Husary (server-side default)
            const selectedVersions = getSelectedMushafVersions();
            const params = new URLSearchParams();
            selectedVersions.forEach(v => params.append('version', v));
            const qs = params.toString() ? '?' + params.toString() : '';

            const data = await fetchData(`/api/recitation-guide/${surah}/${ayah}${qs}`);
            const verseKey = `${surah}:${ayah}`;
            const verseText = quranTextData?.[verseKey]?.text || currentAyahData?.text || '';
            buildRecitationGuideHTML(guideContainer, verseText, data.guide || [], data.versions || []);
        } catch (error) {
            guideContainer.innerHTML = '<div class="guide-error"><i class="fas fa-triangle-exclamation"></i> خطأ في تحميل دليل التلاوة</div>';
            console.error('Recitation guide error:', error);
        }
    }

    function buildRecitationGuideHTML(container, verseText, waqfData, versions) {
        container.innerHTML = '';
        const words = (verseText || '').split(' ').filter(w => w.trim());

        // ── No waqf data → read to end of verse ──────────────────────────
        if (!waqfData || waqfData.length === 0) {
            const noWaqfEl = document.createElement('div');
            noWaqfEl.className = 'guide-no-waqf';
            noWaqfEl.innerHTML =
                `<span class="guide-no-waqf-sym">۝</span>` +
                `<span class="guide-no-waqf-title">لا توجد علامات وقف لهذه الآية</span>` +
                `<span class="guide-no-waqf-body">اقرأ الآية كاملةً دون وقف، ثم قف عند رأس الآية <span style="font-family:'UthmanicHafs',serif;font-size:1.1rem">۝</span></span>`;
            container.appendChild(noWaqfEl);
            return;
        }

        // ── Build waqf map: tokenIndex → [{symbols, version}] ────────────
        const waqfMap = buildWaqfByTokenIndex(waqfData, words);

        // ── Group words into reading segments ─────────────────────────────
        const segments = [];
        let currentWords = [];
        for (let i = 0; i < words.length; i++) {
            currentWords.push(words[i]);
            const entries = waqfMap.get(i);
            if (entries && entries.length > 0) {
                segments.push({ words: [...currentWords], waqf: entries });
                currentWords = [];
            }
        }
        if (currentWords.length > 0) {
            segments.push({ words: currentWords, waqf: null });
        }

        // ── Wrapper ───────────────────────────────────────────────────────
        const wrapper = document.createElement('div');
        wrapper.className = 'recitation-guide';

        // Title
        const versionLabel = versions && versions.length ? versions.join(' + ') : 'الحصري';
        const titleEl = document.createElement('div');
        titleEl.className = 'guide-title';
        titleEl.innerHTML = `<i class="fas fa-route"></i> دليل التلاوة — وقف ${versionLabel}`;
        wrapper.appendChild(titleEl);

        const subtitleEl = document.createElement('p');
        subtitleEl.className = 'guide-subtitle';
        subtitleEl.textContent = 'الآية مقسّمة إلى مقاطع وفق مواضع الوقف. اقرأ كل مقطع حتى الرمز ثم قف أو استمر حسب الحكم.';
        wrapper.appendChild(subtitleEl);

        // ── Segments ──────────────────────────────────────────────────────
        const segRow = document.createElement('div');
        segRow.className = 'guide-seg-row';
        segRow.dir = 'rtl';

        segments.forEach((seg, idx) => {
            const segEl = document.createElement('div');
            segEl.className = 'guide-segment';
            if (!seg.waqf) segEl.classList.add('guide-segment-last');

            // Segment number
            const segNum = document.createElement('span');
            segNum.className = 'guide-seg-num';
            segNum.textContent = String(idx + 1);
            segEl.appendChild(segNum);

            // Verse words
            const wordsEl = document.createElement('div');
            wordsEl.className = 'guide-seg-words';
            wordsEl.dir = 'rtl';
            wordsEl.textContent = seg.words.map(w => stripEmbeddedWaqf(w)).join(' ');
            segEl.appendChild(wordsEl);

            // Waqf badges — grouped by unique symbol+version combination
            if (seg.waqf) {
                const waqfEl = document.createElement('div');
                waqfEl.className = 'guide-seg-waqf';

                seg.waqf.forEach(entry => {
                    const raw = (entry.symbols || '').trim();
                    const normalized = normalizeNonWarshWaqfText(raw);
                    const isLatin = /[\u21BA\u25B6]/.test(normalized);
                    const info = getWaqfInfo(raw);
                    const mushafCls = isLatin ? 'waqf-color-latin' : getMushafColorClass(entry.version);

                    // Symbol glyph
                    const symSpan = document.createElement('span');
                    symSpan.className = 'guide-waqf-sym ' + mushafCls;
                    symSpan.textContent = normalized || raw;
                    waqfEl.appendChild(symSpan);

                    // Mushaf badge pill (colored by mushaf)
                    if (entry.version) {
                        const badge = document.createElement('span');
                        badge.className = 'guide-mushaf-badge ' + mushafCls;
                        badge.textContent = entry.version;
                        waqfEl.appendChild(badge);
                    }

                    // Waqf type meaning label (neutral gray)
                    const lblSpan = document.createElement('span');
                    lblSpan.className = 'guide-waqf-lbl';
                    lblSpan.textContent = info.meaning;
                    waqfEl.appendChild(lblSpan);
                });

                segEl.appendChild(waqfEl);

                // Arrow connector
                const arrow = document.createElement('div');
                arrow.className = 'guide-seg-arrow';
                arrow.innerHTML = '<i class="fas fa-arrow-left"></i>';
                segEl.appendChild(arrow);
            }

            segRow.appendChild(segEl);
        });

        wrapper.appendChild(segRow);

        // ── Legend: show which mushafs are present ─────────────────────────
        const seenVersions = [...new Set(waqfData.map(e => e.version).filter(Boolean))];
        if (seenVersions.length > 0) {
            const legendEl = document.createElement('div');
            legendEl.className = 'guide-legend';
            legendEl.innerHTML = '<span class="guide-legend-title">الألوان:</span>' +
                seenVersions.map(v => {
                    const cls = getMushafColorClass(v);
                    return `<span class="guide-legend-item">` +
                        `<span class="guide-waqf-sym ${cls}" style="font-size:0.85rem">●</span> ${v}` +
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
        wordElement.textContent = (mode === 'selected' || mode === 'none') ? cleanText : word;
        wordElement.dataset.index = index;
        wordElement.addEventListener('click', () => playWordSegment(index, wordIndexToSegmentMap));
        return wordElement;
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
        currentRepeatCount++;
        
        if (currentRepeatCount < maxRepeats) {
            elements.audioElement.currentTime = 0;
            elements.audioElement.play();
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
                    elements.ayahSelect.selectedIndex++;
                    await loadQuranData();
                    elements.audioElement.play();
                    updatePlayPauseButton();
                } else {
                    // Clean up when range ends
                    cleanupRangeMode();
                    updatePlayPauseButton();
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
        if (font !== 'digital_khatt') {
            quranText.classList.add(font);
        } else {
            quranText.classList.add('digital_khatt');
        }
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
        
        if (elements.audioElement.paused) {
            elements.playPauseButton.classList.remove('fa-pause');
            elements.playPauseButton.classList.add('fa-play');
        } else {
            elements.playPauseButton.classList.remove('fa-play');
            elements.playPauseButton.classList.add('fa-pause');
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
});
