document.addEventListener('DOMContentLoaded', async () => {
    const elements = getElements();
    const reciterAudioDataMap = {};
    let quranTextData;
    let currentSegments = [];
    let currentAyahData = null; // Cache for current ayah data
    let currentRepeatCount = 0; // Track current repeat count
    let maxRepeats = 1; // Track maximum repeats set by user
    const fontCache = {};

    // Load user preferences from localStorage
    loadUserPreferences();
    
    addEventListeners();

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
    }

    // Initialize voice recognition with error handling
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
        console.warn('Web Speech API is not supported in this browser.');
        // Optionally disable the voice command button
        const voiceButton = document.getElementById('start-voice-command');
        if (voiceButton) {
            voiceButton.disabled = true;
            voiceButton.title = 'Speech recognition not supported in this browser';
        }
    }

    async function handleVoiceCommand(command) {
        console.log('Voice command received:', command);

        try {
            const surahMatch = command.match(/chapter (\d+)/);
            const ayahMatch = command.match(/verse (\d+)/);

            if (surahMatch) {
                const surahNumber = parseInt(surahMatch[1], 10);
                if (surahNumber >= 1 && surahNumber <= 114) {
                    elements.surahSelect.value = surahNumber;
                    await loadAyahs();
                    // If an Ayah is also specified in the command, update it after loading Ayahs
                    if (ayahMatch) {
                        const ayahNumber = parseInt(ayahMatch[1], 10);
                        if (ayahNumber >= 1) {
                            elements.ayahSelect.value = ayahNumber;
                            await loadQuranData(surahNumber, ayahNumber);
                        }
                    }
                } else {
                    console.warn('Invalid surah number:', surahNumber);
                }
            } else if (ayahMatch) {
                const ayahNumber = parseInt(ayahMatch[1], 10);
                if (ayahNumber >= 1) {
                    elements.ayahSelect.value = ayahNumber;
                    await loadQuranData(elements.surahSelect.value, ayahNumber);
                } else {
                    console.warn('Invalid ayah number:', ayahNumber);
                }
            }
        } catch (error) {
            console.error('Error handling voice command:', error);
        }
    }

    // Initialize Tippy.js on the button with fallback
    try {
        if (typeof tippy !== 'undefined') {
            tippy('#start-voice-command', {
                content: ' لطريقة اسرع للتنقل بين السور والايات المختلفة استخدم الاوامر الصوتية بهذا الشكل " Go to chapter ---  verse " ',
                placement: 'top',
            });
        }
    } catch (error) {
        console.warn('Tippy.js not loaded, tooltips disabled:', error);
    }
    
    async function loadInitialData() {
        await loadSurahData();
        await loadQuranTextData();
        updateGlobalAyahToVerseKey();
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
            modalContent: document.querySelector('.modal-content'),
            closeModal: document.getElementsByClassName('close')[0],
            quranTextSelect: document.getElementById('quran-text-select'),
            playPauseButton: document.getElementById('play-pause-button'),
            toggleWordMeaningButton: document.getElementById('toggle-word-meaning-button'),
            bookmarkButton: document.getElementById('bookmark-button'),
            showBookmarksButton: document.getElementById('show-bookmarks-button'),
            bookmarksModal: document.getElementById('bookmarksModal'),
            bookmarksList: document.getElementById('bookmarks-list'),
            closeBookmarksModal: document.getElementsByClassName('close-bookmarks')[0]
        };
    }

    function addEventListeners() {
        elements.darkModeToggle.addEventListener('change', toggleDarkMode);
        elements.sepiaModeToggle.addEventListener('change', toggleSepiaMode);
        elements.showRangeSelection.addEventListener('click', toggleRangeSelection);
        elements.reciterSelect.addEventListener('change', onReciterChange);
        elements.surahSelect.addEventListener('change', loadAyahs);
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
        elements.showRangeSelection.onclick = showModal;
        elements.closeModal.onclick = closeModal;
        window.onclick = (event) => {
            if (event.target == elements.modal) closeModal();
        };
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
        if (!fontCache[font]) {
            quranTextData = await fetchData(`/api/quran-text?source=${font}`);
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
            currentAyahData = await fetchData(`/api/surahs/${surahNumber}/ayahs/${ayahNumber}`);
            const verseKey = `${surahNumber}:${ayahNumber}`;
            const globalAyahNumber = currentAyahData.id;
            if (!globalAyahNumber) throw new Error(`No global Ayah number found for Surah ${surahNumber}, Ayah ${ayahNumber}`);
    
            const reciter = elements.reciterSelect.value;
            const reciterAudio = currentAyahData.reciters[reciter];
            if (!reciterAudio) throw new Error('Reciter audio not found');
    
            const font = elements.quranTextSelect.value;
            // Use already cached quranTextData instead of making redundant API call
            const ayahText = quranTextData?.[verseKey]?.text || currentAyahData.text;
    
            elements.audioElement.src = `/api/audio-proxy?url=${encodeURIComponent(reciterAudio.audio_url)}`;
            currentSegments = reciterAudio.segments;
            displayQuranicText(ayahText, currentSegments, currentAyahData.word_meanings);
            displayTransliteration(currentAyahData.transliteration);
            displayTafseers(currentAyahData.tafseer || {});
            // Only display word meanings if they should be visible
            if (elements.wordMeaningVisible) {
                displayWordMeanings(currentAyahData.word_meanings || {}, ayahText);
            } else {
                elements.wordMeaningContainer.innerHTML = '';
            }
            updatePlayPauseButton();
            
            // Save current position to localStorage
            saveUserPreferences();
            
            // Preload next ayah for low latency navigation
            preloadNextAyah();
    
            elements.audioElement.onended = updatePlayPauseButton;
        } catch (error) {
            handleError('Error loading Quran data:', error, elements.quranTextContainer, 'خطأ في تحميل البيانات. يرجى المحاولة مرة أخرى لاحقًا.');
        }
    }

    async function updateDisplayedText() {
        const surahNumber = elements.surahSelect.value;
        const ayahNumber = elements.ayahSelect.value;
        if (!ayahNumber) return;

        try {
            // Use cached data if available, otherwise fetch
            if (!currentAyahData || currentAyahData.surah_number !== parseInt(surahNumber) || currentAyahData.ayah_number !== parseInt(ayahNumber)) {
                currentAyahData = await fetchData(`/api/surahs/${surahNumber}/ayahs/${ayahNumber}`);
            }
            
            const verseKey = `${surahNumber}:${ayahNumber}`;
            // Use already cached quranTextData instead of making redundant API call
            const ayahText = quranTextData?.[verseKey]?.text || currentAyahData.text;
            displayQuranicText(ayahText, currentSegments, currentAyahData.word_meanings);
            displayTransliteration(currentAyahData.transliteration);
            displayTafseers(currentAyahData.tafseer || {});
            if (elements.wordMeaningVisible) {
                displayWordMeanings(currentAyahData.word_meanings || {}, ayahText);
            } else {
                elements.wordMeaningContainer.innerHTML = '';
            }
        } catch (error) {
            handleError('Error updating Quran text:', error, elements.quranTextContainer, 'خطأ في تحديث النص. يرجى المحاولة مرة أخرى لاحقًا.');
        }
    }

    function displayQuranicText(text, segments) {
        elements.quranTextContainer.innerHTML = '';
        const words = text.split(' ');
        const wordIndexToSegmentMap = new Map();
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

    function toggleTafseer() {
        const tafseerContainer = document.getElementById('tafseer-container');
        tafseerContainer.style.display = tafseerContainer.style.display === 'none' ? 'block' : 'none';
        updateTafseerButton();
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

    function createWordElement(word, index, wordIndexToSegmentMap) {
        const wordElement = document.createElement('span');
        wordElement.textContent = word;
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
        // Clear sepia mode if it's active
        if (document.body.classList.contains('sepia-mode')) {
            document.body.classList.remove('sepia-mode');
            const container = document.querySelector('.container');
            if (container) container.classList.remove('sepia-mode');
            document.querySelectorAll('button, select, input, audio').forEach(element => {
                element.classList.remove('sepia-mode');
            });
            elements.sepiaModeToggle.checked = false;
        }
        
        const elementsToToggle = ['body', '.container'];
        const selectors = ['button', 'select', 'input', 'audio'];
        
        elementsToToggle.forEach(element => {
            const el = element === 'body' ? document.body : document.querySelector(element);
            if (el) el.classList.toggle('dark-mode');
        });
        
        selectors.forEach(selector => {
            document.querySelectorAll(selector).forEach(element => {
                if (element) element.classList.toggle('dark-mode');
            });
        });
        
        // Save theme preference
        if (document.body.classList.contains('dark-mode')) {
            localStorage.setItem('quranApp_theme', 'dark');
        } else {
            localStorage.setItem('quranApp_theme', 'light');
        }
    }

    function toggleSepiaMode() {
        // Clear dark mode if it's active
        if (document.body.classList.contains('dark-mode')) {
            document.body.classList.remove('dark-mode');
            const container = document.querySelector('.container');
            if (container) container.classList.remove('dark-mode');
            document.querySelectorAll('button, select, input, audio').forEach(element => {
                element.classList.remove('dark-mode');
            });
            elements.darkModeToggle.checked = false;
        }
        
        const elementsToToggle = ['body', '.container'];
        const selectors = ['button', 'select', 'input', 'audio'];
        
        elementsToToggle.forEach(element => {
            const el = element === 'body' ? document.body : document.querySelector(element);
            if (el) el.classList.toggle('sepia-mode');
        });
        
        selectors.forEach(selector => {
            document.querySelectorAll(selector).forEach(element => {
                if (element) element.classList.toggle('sepia-mode');
            });
        });
        
        // Save theme preference
        if (document.body.classList.contains('sepia-mode')) {
            localStorage.setItem('quranApp_theme', 'sepia');
        } else {
            localStorage.setItem('quranApp_theme', 'light');
        }
    }

    function toggleRangeSelection() {
        if (elements.rangeSelection) {
            elements.rangeSelection.style.display = elements.rangeSelection.style.display === 'none' ? 'block' : 'none';
        }
    }

    function showModal() {
        elements.modal.classList.add('show');
        elements.modalContent.classList.add('show');
    }

    function closeModal() {
        elements.modal.classList.remove('show');
        elements.modalContent.classList.remove('show');
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
        elements.bookmarkButton.innerHTML = '<i class="fas fa-check"></i> تم الحفظ';
        setTimeout(() => {
            elements.bookmarkButton.innerHTML = '<i class="fas fa-bookmark"></i> علامة مرجعية';
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
