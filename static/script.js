document.addEventListener('DOMContentLoaded', async () => {
    const elements = getElements();
    const reciterAudioDataMap = {};
    let quranTextData;
    let currentSegments = [];
    const fontCache = {};

    addEventListeners();

    try {
        await loadInitialData();
    } catch (error) {
        handleError('Error loading data:', error, elements.quranTextContainer, 'خطأ في تحميل البيانات. يرجى المحاولة مرة أخرى لاحقًا.');
    }

    // Initialize voice recognition
    if ('webkitSpeechRecognition' in window) {
        const recognition = new webkitSpeechRecognition();
        recognition.lang = 'en-US';
        recognition.continuous = false;
        recognition.interimResults = false;

        recognition.onresult = function(event) {
            const transcript = event.results[0][0].transcript.toLowerCase();
            handleVoiceCommand(transcript);
        };

        recognition.onerror = function(event) {
            console.error('Speech recognition error:', event.error);
        };

        document.getElementById('start-voice-command').addEventListener('click', () => {
            recognition.start();
        });
    } else {
        console.warn('Web Speech API is not supported in this browser.');
    }

    async function handleVoiceCommand(command) {
        console.log('Voice command received:', command);

        const surahMatch = command.match(/chapter (\d+)/);
        const ayahMatch = command.match(/verse (\d+)/);

        if (surahMatch) {
            const surahNumber = parseInt(surahMatch[1], 10);
            elements.surahSelect.value = surahNumber;
            await loadAyahs();
            // If an Ayah is also specified in the command, update it after loading Ayahs
            if (ayahMatch) {
                const ayahNumber = parseInt(ayahMatch[1], 10);
                elements.ayahSelect.value = ayahNumber;
                await loadQuranData(surahNumber, ayahNumber);
            }
        } else if (ayahMatch) {
            const ayahNumber = parseInt(ayahMatch[1], 10);
            elements.ayahSelect.value = ayahNumber;
            await loadQuranData(elements.surahSelect.value, ayahNumber);
        }
    }

    // Initialize Tippy.js on the button
    tippy('#start-voice-command', {
        content: ' لطريقة اسرع للتنقل بين السور والايات المختلفة استخدم الاوامر الصوتية بهذا الشكل " Go to chapter ---  verse " ',
        placement: 'top',
    });
    
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
            loopSwitch: document.getElementById('loopSwitch'),
            reciterSelect: document.getElementById('reciter-select'),
            surahSelect: document.getElementById('surah-select'),
            ayahSelect: document.getElementById('ayah-select'),
            startAyahSelect: document.getElementById('start-ayah-select'),
            endAyahSelect: document.getElementById('end-ayah-select'),
            nextAyahButton: document.getElementById('next-ayah'),
            prevAyahButton: document.getElementById('prev-ayah'),
            playRangeButton: document.getElementById('play-range'),
            darkModeToggle: document.getElementById('dark-mode-toggle'),
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
        elements.showRangeSelection.addEventListener('click', toggleRangeSelection);
        elements.reciterSelect.addEventListener('change', onReciterChange);
        elements.surahSelect.addEventListener('change', loadAyahs);
        elements.ayahSelect.addEventListener('change', loadQuranData);
        elements.nextAyahButton.addEventListener('click', loadNextAyah);
        elements.prevAyahButton.addEventListener('click', loadPrevAyah);
        elements.playRangeButton.addEventListener('click', playRange);
        elements.showRangeSelection.onclick = showModal;
        elements.closeModal.onclick = closeModal;
        window.onclick = (event) => {
            if (event.target == elements.modal) closeModal();
        };
        elements.quranTextSelect.addEventListener('change', async () => {
            changeFont(elements.quranTextSelect.value);
            await loadQuranTextData();
            await updateDisplayedText();
        });
        elements.playPauseButton.addEventListener('click', togglePlayPause);
        //elements.downloadButton.addEventListener('click', downloadAudio);

        document.getElementById('show-transliteration').addEventListener('click', toggleTransliteration);
        document.getElementById('show-tafseer').addEventListener('click', toggleTafseer);
        elements.toggleWordMeaningButton.addEventListener('click', toggleWordMeaning); // Listener for the new toggle via button
    }

    async function onReciterChange() {
        await loadQuranData();
        updatePlayPauseButton();
    }

    async function loadSurahData() {
        const surahData = await fetchData('https://api.alquran.cloud/v1/surah');
        const formattedSurahData = surahData.data.map(surah => ({
            number: surah.number,
            name: `${surah.number}. ${surah.name}`
        }));
        populateSelectOptions(formattedSurahData, elements.surahSelect, 'number', 'name');
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
            const ayahData = await fetchData(`/api/surahs/${surahNumber}/ayahs/${ayahNumber}`);
            const verseKey = `${surahNumber}:${ayahNumber}`;
            const globalAyahNumber = ayahData.id;
            if (!globalAyahNumber) throw new Error(`No global Ayah number found for Surah ${surahNumber}, Ayah ${ayahNumber}`);
    
            const reciter = elements.reciterSelect.value;
            const reciterAudio = ayahData.reciters[reciter];
            if (!reciterAudio) throw new Error('Reciter audio not found');
    
            console.log('Quran Text Data:', ayahData);
            console.log('Reciter Audio:', reciterAudio);
            console.log('Current Segments:', reciterAudio.segments);
            console.log('Transliteration:', ayahData.transliteration);
            console.log('Tafseers:', ayahData.tafseer);
            console.log('Word Meanings:', ayahData.word_meanings);
    
            const font = elements.quranTextSelect.value;
            const quranTextUrl = `/api/quran-text?source=${font}`;
            const quranTextData = await fetchData(quranTextUrl);
            const ayahText = quranTextData[verseKey]?.text || ayahData.text;
    
            elements.audioElement.src = reciterAudio.audio_url;
            currentSegments = reciterAudio.segments;
            displayQuranicText(ayahText, currentSegments, ayahData.word_meanings);
            displayTransliteration(ayahData.transliteration);
            displayTafseers(ayahData.tafseer || {});
            displayWordMeanings(ayahData.word_meanings || {});
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
            const ayahData = await fetchData(`/api/surahs/${surahNumber}/ayahs/${ayahNumber}`);
            const verseKey = `${surahNumber}:${ayahNumber}`;
            const font = elements.quranTextSelect.value;
            const quranTextUrl = `/api/quran-text?source=${font}`;
            const quranTextData = await fetchData(quranTextUrl);
            const ayahText = quranTextData[verseKey]?.text || ayahData.text;
            displayQuranicText(ayahText, currentSegments, ayahData.word_meanings);
            displayTransliteration(ayahData.transliteration);
            displayTafseers(ayahData.tafseer || {});
            if (elements.wordMeaningVisible) {
                displayWordMeanings(ayahData.word_meanings || {});
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

        for (let i = 0; i < words.length; i++) {
            const word = words[i];
            const wordElement = createWordElement(word, i, wordIndexToSegmentMap);
            elements.quranTextContainer.appendChild(wordElement);
            elements.quranTextContainer.appendChild(document.createTextNode(' '));
        }

        if (Array.isArray(segments)) {
            mapSegmentsToWords(segments, wordIndexToSegmentMap);
        } else {
            console.error('Invalid segments format:', segments);
        }

        elements.audioElement.addEventListener('timeupdate', () => {
            highlightWords(words, wordIndexToSegmentMap);
        });
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

    function displayWordMeanings(wordMeanings) {
        if (elements.wordMeaningContainer) {
            elements.wordMeaningContainer.innerHTML = '';
            const entries = Object.entries(wordMeanings);
            if (entries.length > 0) {
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
        segments.forEach(segment => {
            if (typeof segment === 'object' && segment !== null) {
                const { start_word_index, end_word_index, start_time, end_time } = segment;
                for (let i = parseInt(start_word_index); i <= parseInt(end_word_index); i++) {
                    wordIndexToSegmentMap.set(i, { startTime: parseInt(start_time), endTime: parseInt(end_time) });
                }
            } else {
                console.error('Invalid segment format:', segment);
            }
        });
    }

    function highlightWords(words, wordIndexToSegmentMap) {
        const currentTime = elements.audioElement.currentTime * 1000;
        words.forEach((_, index) => {
            const wordElement = elements.quranTextContainer.querySelector(`[data-index="${index}"]`);
            if (!wordElement) return;
            const segment = wordIndexToSegmentMap.get(index);
            if (segment && currentTime >= segment.startTime && currentTime <= segment.endTime) {
                wordElement.classList.add('highlight');
            } else {
                wordElement.classList.remove('highlight');
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
        const currentAyahIndex = elements.ayahSelect.selectedIndex;
        if (currentAyahIndex < elements.ayahSelect.options.length - 1) {
            elements.ayahSelect.selectedIndex = currentAyahIndex + 1;
            await loadQuranData();
            elements.audioElement.play();
            updatePlayPauseButton();
        }
    }

    async function loadPrevAyah() {
        const currentAyahIndex = elements.ayahSelect.selectedIndex;
        if (currentAyahIndex > 0) {
            elements.ayahSelect.selectedIndex = currentAyahIndex - 1;
            await loadQuranData();
            elements.audioElement.play();
            updatePlayPauseButton();
        }
    }

    function toggleLoopSwitch() {
        updatePlayPauseButton();
    }
    
    elements.loopSwitch.addEventListener('change', toggleLoopSwitch);
    
    elements.audioElement.addEventListener('ended', () => {
        if (elements.loopSwitch.checked) {
            elements.audioElement.currentTime = 0;
            elements.audioElement.play();
        } else {
            updatePlayPauseButton();
        }
    });


    function toggleDarkMode() {
        document.body?.classList.toggle('dark-mode');
        document.querySelector('.container')?.classList.toggle('dark-mode');
        document.querySelectorAll('button, select').forEach(element => {
            element?.classList.toggle('dark-mode');
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

            const onEnded = async () => {
                if (elements.ayahSelect.selectedIndex < endAyahIndex) {
                    elements.ayahSelect.selectedIndex++;
                    await loadQuranData();
                    elements.audioElement.play();
                    updatePlayPauseButton();
                } else {
                    elements.audioElement.removeEventListener('ended', onEnded);
                    updatePlayPauseButton();
                }
            };

            elements.audioElement.addEventListener('ended', onEnded);

            const onPlayPause = () => {
                if (elements.audioElement.paused) {
                    elements.audioElement.play();
                } else {
                    elements.audioElement.pause();
                }
                updatePlayPauseButton();
            };

            elements.playPauseButton.addEventListener('click', onPlayPause);

            // Clean up event listeners when range ends
            elements.audioElement.addEventListener('ended', () => {
                elements.playPauseButton.removeEventListener('click', onPlayPause);
            });
        }
    }

    function populateSelectOptions(data, selectElement, valueKey, textKey, prefix = '') {
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
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        return response.json();
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
        if (elements.audioElement.paused) {
            elements.audioElement.play();
            elements.playPauseButton.classList.remove('fa-play');
            elements.playPauseButton.classList.add('fa-pause');
        } else {
            elements.audioElement.pause();
            elements.playPauseButton.classList.remove('fa-pause');
            elements.playPauseButton.classList.add('fa-play');
        }
    }

    function updatePlayPauseButton() {
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
