document.addEventListener('DOMContentLoaded', async () => {
    const elements = getElements();
    const reciterAudioDataMap = {};
    let quranTextData;
    let currentSegments = [];

    addEventListeners();

    try {
        await loadInitialData();
    } catch (error) {
        handleError('Error loading data:', error, elements.quranTextContainer, 'خطأ في تحميل البيانات. يرجى المحاولة مرة أخرى لاحقًا.');
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
            audioElement: document.getElementById('quran-audio'),
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
            downloadButton: document.getElementById('download-button')
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
        elements.downloadButton.addEventListener('click', downloadAudio);

        document.getElementById('show-transliteration').addEventListener('click', toggleTransliteration);
        document.getElementById('show-tafseer').addEventListener('click', toggleTafseer);
    }

    async function onReciterChange() {
        const currentSurah = elements.surahSelect.value;
        const currentAyah = elements.ayahSelect.value;
        await loadAyahs();
        elements.surahSelect.value = currentSurah;
        elements.ayahSelect.value = currentAyah;
        await loadQuranData();
        updatePlayPauseButton();
    }

    async function loadSurahData() {
        const surahData = await fetchData('https://api.alquran.cloud/v1/surah');
        populateSelectOptions(surahData.data, elements.surahSelect, 'number', 'name');
    }

    async function loadQuranTextData() {
        const font = elements.quranTextSelect.value;
        quranTextData = await fetchData(`/api/quran-text?source=${font}`);
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

            // Fetch Quran text data based on selected font
            const font = elements.quranTextSelect.value;
            const quranTextUrl = `/api/quran-text?source=${font}`;
            const quranTextData = await fetchData(quranTextUrl);
            const ayahText = quranTextData[verseKey]?.text || ayahData.text;
    
            elements.audioElement.src = reciterAudio.audio_url;
            currentSegments = reciterAudio.segments;
            displayQuranicText(ayahText, currentSegments);
            displayTransliteration(ayahData.transliteration);
            displayTafseers(ayahData.tafseer || {}); // Ensure tafseer is an object
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
            displayQuranicText(ayahText, currentSegments);
        } catch (error) {
            handleError('Error updating Quran text:', error, elements.quranTextContainer, 'خطأ في تحديث النص. يرجى المحاولة مرة أخرى لاحقًا.');
        }
    }

    function displayQuranicText(text, segments) {
        elements.quranTextContainer.innerHTML = '';
        const words = text.split(' ');
        const wordIndexToSegmentMap = new Map();

        words.forEach((word, index) => {
            const wordElement = createWordElement(word, index, wordIndexToSegmentMap);
            elements.quranTextContainer.appendChild(wordElement);
            elements.quranTextContainer.appendChild(document.createTextNode(' '));
        });

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
    
                // Prepare data for populateSelectOptions
                const tafseerArray = Object.keys(tafseers).map(tafseerName => ({
                   value: tafseerName,
                   text: tafseerName
                }));
                // Use populateSelectOptions to populate the select element
                populateSelectOptions(tafseerArray, selectElement, 'value', 'text');
    
                // Check if there's a previously selected tafseer
                const previouslySelectedTafseer = localStorage.getItem('selectedTafseer');
                if (previouslySelectedTafseer && tafseers[previouslySelectedTafseer]) {
                    selectElement.value = previouslySelectedTafseer;
                }
    
                selectElement.addEventListener('change', () => {
                    const selectedValue = selectElement.value;
                    const selectedTafseer = tafseers[selectedValue] || { text: 'No tafseer available' };
                    tafseerTextElement.innerHTML = selectedTafseer.text;
                    console.log('Selected Tafseer:', JSON.stringify(selectedTafseer)); // Log the selected tafseer
                    // Save the selected tafseer to localStorage
                    localStorage.setItem('selectedTafseer', selectedValue);
                });
    
                // Trigger change event to display the selected or first tafseer by default
                selectElement.dispatchEvent(new Event('change'));
            } else {
                elements.tafseerContainer.innerHTML = 'No tafseer available';
            }
        }
    }

    function toggleTransliteration() {
        const transliterationContainer = document.getElementById('transliteration-container');
        transliterationContainer.style.display = transliterationContainer.style.display === 'none' ? 'block' : 'none';
    }

    function toggleTafseer() {
        const tafseerContainer = document.getElementById('tafseer-container');
        tafseerContainer.style.display = tafseerContainer.style.display === 'none' ? 'block' : 'none';
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
        const currentTime = elements.audioElement.currentTime * 1000; // Convert to milliseconds
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
            elements.audioElement.currentTime = segment.startTime / 1000; // Convert to seconds
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
            closeModal(); // Close the modal immediately after clicking play

            elements.audioElement.addEventListener('ended', async function onEnded() {
                if (elements.ayahSelect.selectedIndex < endAyahIndex) {
                    elements.ayahSelect.selectedIndex++;
                    await loadQuranData();
                    elements.audioElement.play();
                    updatePlayPauseButton();
                } else {
                    elements.audioElement.removeEventListener('ended', onEnded);
                    updatePlayPauseButton();
                }
            });

            elements.playPauseButton.addEventListener('click', function onPlayPause() {
                if (elements.audioElement.paused) {
                    elements.audioElement.play();
                } else {
                    elements.audioElement.pause();
                }
                updatePlayPauseButton();
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
        quranText.className = 'digital_khatt'; // Set base class
        if (font !== 'digital_khatt') {
            quranText.classList.add(font);
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

    async function downloadAudio() {
        const response = await fetch(elements.audioElement.src);
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'quran_audio.mp3';
        link.click();
        URL.revokeObjectURL(url); // Clean up the URL object
    }

    // async function loadRandomAyah() {
    //     const surahData = await fetchData('https://api.alquran.cloud/v1/surah');
    //     const randomSurah = surahData.data[Math.floor(Math.random() * surahData.data.length)];
    //     const ayahData = await fetchData(`https://api.alquran.cloud/v1/surah/${randomSurah.number}`);
    //     const randomAyah = ayahData.data.ayahs[Math.floor(Math.random() * ayahData.data.ayahs.length)];

    //     elements.surahSelect.value = randomSurah.number;
    //     await loadAyahs();
    //     elements.ayahSelect.value = randomAyah.number;
    //     await loadQuranData();
    // }

    loadAyahs();
});
