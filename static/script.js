document.addEventListener('DOMContentLoaded', async () => {
    const elements = getElements();
    const reciterAudioDataMap = {};
    let quranTextData;
    let currentSegments = [];
    let currentAyahData = null; // Cache for current ayah data
    let currentRepeatCount = 0; // Track current repeat count
    let maxRepeats = 1; // Track maximum repeats set by user
    const fontCache = {};

    addEventListeners();

    try {
        await loadInitialData();
        // Initialize repeat functionality
        handleRepeatChange();
    } catch (error) {
        handleError('Error loading data:', error, elements.quranTextContainer, 'خطأ في تحميل البيانات. يرجى المحاولة مرة أخرى لاحقًا.');
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
            wordMeaningContainer: document.getElementById('word-meaning-text'), // New container for word meanings
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
            toggleWordMeaningButton: document.getElementById('toggle-word-meaning-button'), // Updated element for toggling word meanings
           // downloadButton: document.getElementById('download-button')
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
        //elements.downloadButton.addEventListener('click', downloadAudio);

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
            const surahData = await fetchData('https://api.alquran.cloud/v1/surah');
            const formattedSurahData = surahData.data.map(surah => ({
                number: surah.number,
                name: `${surah.number}. ${surah.name}`
            }));
            populateSelectOptions(formattedSurahData, elements.surahSelect, 'number', 'name');
        } catch (error) {
            console.error('Error loading surah data from external API:', error);
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
            await loadQuranData();
            updatePlayPauseButton();
        } catch (error) {
            handleError('Error loading Ayahs:', error, elements.quranTextContainer, 'خطأ في تحميل الآيات. يرجى المحاولة مرة أخرى لاحقًا.');
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
    
            console.log('Quran Text Data:', currentAyahData);
            console.log('Reciter Audio:', reciterAudio);
            console.log('Current Segments:', reciterAudio.segments);
            console.log('Transliteration:', currentAyahData.transliteration);
            console.log('Tafseers:', currentAyahData.tafseer);
            console.log('Word Meanings:', currentAyahData.word_meanings);
    
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

                selectElement.addEventListener('change', () => {
                    const selectedValue = selectElement.value;
                    const selectedTafseer = tafseers[selectedValue] || { text: 'No tafseer available' };
                    tafseerTextElement.innerHTML = selectedTafseer.text;
                    console.log('Selected Tafseer:', JSON.stringify(selectedTafseer));
                    localStorage.setItem('selectedTafseer', selectedValue);
                });

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
                
                // Create ordered list based on verse word sequence
                verseWords.forEach(verseWord => {
                    // Clean the verse word by removing diacritics and numbers for better matching
                    const cleanVerseWord = verseWord.replace(/[٠-٩0-9]/g, '').trim();
                    
                    // Find matching word in meanings (try exact match first, then partial)
                    let matchingEntry = null;
                    for (const [word, meaning] of entries) {
                        if (word === cleanVerseWord || word === verseWord) {
                            matchingEntry = [word, meaning];
                            break;
                        }
                    }
                    
                    // If exact match not found, try finding word that contains the verse word or vice versa
                    if (!matchingEntry) {
                        for (const [word, meaning] of entries) {
                            if (word.includes(cleanVerseWord) || cleanVerseWord.includes(word)) {
                                matchingEntry = [word, meaning];
                                break;
                            }
                        }
                    }
                    
                    if (matchingEntry) {
                        const [word, meaning] = matchingEntry;
                        const listItem = document.createElement('li');
                        listItem.textContent = `${word}: ${meaning}`;
                        list.appendChild(listItem);
                        // Remove from entries to avoid duplicates
                        const index = entries.findIndex(([w, m]) => w === word && m === meaning);
                        if (index > -1) {
                            entries.splice(index, 1);
                        }
                    }
                });
                
                // Add any remaining meanings that weren't matched (shouldn't happen in normal cases)
                entries.forEach(([word, meaning]) => {
                    const listItem = document.createElement('li');
                    listItem.textContent = `${word}: ${meaning}`;
                    list.appendChild(listItem);
                });
                
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

    // Initialize word meanings visibility
    elements.wordMeaningVisible = false;
    elements.wordMeaningContainer.style.display = 'none';
    updateWordMeaningButton();

    loadAyahs();
});
