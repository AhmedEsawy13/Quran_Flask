# Quran_Flask_Vercel

Quran_Flask is a web application that provides access to the Holy Quran. It is built using Flask and deployed on Vercel.

## Features

### 🎨 **Theme & Display**
- **Dark Mode**: Toggle between light and dark themes for comfortable reading
- **Sepia Mode**: Eye-friendly sepia theme for extended reading sessions
- **Multiple Arabic Fonts**: Choose from UthmanicHafs, Digital Khatt, and IndoPak Nastaleeq fonts
- **Responsive Design**: Optimized for both mobile and desktop users
- **Theme Persistence**: Your preferred theme is saved and restored on next visit

### 📖 **Quranic Text Features**
- **Word-by-word Highlighting**: Real-time highlighting of words during audio recitation
- **Word Meanings (غريب الكلمات)**: Display meanings of difficult Arabic words
- **Clickable Words**: Click on any word to hear its individual pronunciation
- **Transliteration**: Show phonetic pronunciation of Arabic text
- **Tafseer Integration**: Access to multiple commentary sources (Al Qurtubi, Al Saddi, Al-Baghawi)

### 🎵 **Advanced Audio Features**
- **Multiple Reciters**: Choose from renowned reciters (Abdul Basit Abdul Samad, Mohamed al-Tablawi, Mohamed al-Minshawi)
- **Audio Synchronization**: Precise word-by-word audio timing
- **Range Selection**: Play multiple consecutive verses
- **Loop Functionality**: Repeat verses for memorization
- **Audio Controls**: Play, pause, next/previous verse navigation
- **Audio Preloading**: Next ayah audio is preloaded for seamless navigation

### 🔖 **Bookmark System**
- **Save Bookmarks**: Bookmark your favorite verses for quick access
- **Manage Bookmarks**: View and delete bookmarks from a modal dialog
- **Quick Navigation**: Click any bookmark to jump directly to that verse

### 🎤 **Interactive Features**
- **Voice Commands**: Control the app using speech recognition (English)
- **Navigation Controls**: Easy verse-by-verse navigation with keyboard shortcuts (Arrow keys)
- **Modal Dialogs**: User-friendly range selection interface
- **Toast Notifications**: Modern notification system for user feedback

### 💾 **User Preferences**
- **Auto-save Position**: Your last viewed verse is remembered
- **Preference Persistence**: Theme, font, and reciter choices are saved locally
- **No Login Required**: All preferences stored in browser localStorage

### 🔧 **Technical Features**
- **RESTful API**: Well-structured API endpoints for data access
- **Caching System**: Optimized performance with intelligent caching
- **Security Headers**: Enhanced security with proper HTTP headers and CSP
- **Error Handling**: Robust error handling and logging
- **SQLite Database**: Local database for word meanings and metadata
- **Local Surah Data**: All 114 surah names stored locally (no external API dependency)

## Performance Optimizations

The application is optimized for deployment on Vercel with:
- **Lazy Loading**: Tafseer files (35MB) loaded on-demand for faster cold starts
- **Response Compression**: GZIP compression reduces API response sizes by ~70%
- **Caching**: Server-side caching with `@lru_cache` and Cache-Control headers
- **Efficient Data Loading**: Only essential data loaded at startup
- **CDN Caching**: Static files cached for 1 year, API responses for 1 hour
- **Audio Preloading**: Next verse audio preloaded for low-latency playback

**Performance Metrics:**
- Cold start time: ~1.5-3 seconds (60-70% improvement)
- Memory usage: ~80MB at startup (68% reduction)
- API response size: ~500KB compressed (75% reduction)

See [OPTIMIZATION_SUMMARY.md](OPTIMIZATION_SUMMARY.md) for detailed information.

   
## Installation

To run this project locally, follow these steps:

1. **Clone the repository:**
   ```bash
   git clone https://github.com/AhmedEsawy13/Quran_Flask.git
   ```

2. **Navigate to the project directory:**
   ```bash
   cd Quran_Flask
   ```

3. **Install the required dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the Flask application:**
   ```bash
   python app.py
   ```
   or
   ```bash
   flask run
   ```

5. **Access the application:**
   Open your browser and go to `http://localhost:5000`

### Requirements
- Python 3.7+
- Flask 3.0.3
- SQLite3 (included with Python)
- Modern web browser with HTML5 support
- Internet connection for external CDN resources

## API Endpoints

The application provides RESTful API endpoints for accessing Quranic data:

### Surahs
- `GET /api/surahs` - Get all surahs (chapters)
- `GET /api/surahs/<surah_number>/ayahs` - Get all ayahs in a surah
- `GET /api/surahs/<surah_number>/ayahs/<ayah_number>` - Get specific ayah with metadata

### Audio & Text
- `GET /api/reciters/<reciter>/ayahs/<ayah_number>/audio` - Get audio data for specific ayah
- `GET /api/quran-text?source=<font_source>` - Get Quranic text in specified font
- `GET /api/audio-proxy?url=<audio_url>` - Proxy for audio streaming

### Search & Discovery
- `GET /api/search?q=<query>&limit=<limit>&source=<source>` - Search verses by text
- `GET /api/word-search?q=<query>&limit=<limit>` - Search word meanings

### Tafseer (Commentary)
- `GET /api/tafseer` - List available tafseers
- `GET /api/tafseer/<tafseer_name>` - Get specific tafseer data

### Monitoring
- `GET /api/health` - Health check endpoint for monitoring service status

### Data Sources
The application uses multiple data sources:
- **QUL_data/Digital_Khatt_Aya_Space.json** - Digital Khatt font text
- **QUL_data/QPC Hafs.json** - UthmanicHafs font text  
- **QUL_data/word_name.db** - SQLite database for word meanings
- External APIs for audio recitations and translations

## Technology Stack

### Backend
- **Flask 3.0.3** - Python web framework
- **SQLite3** - Local database for word meanings
- **JSON Data Files** - Quranic text storage in multiple fonts

### Frontend  
- **Vanilla JavaScript** - No framework dependencies for better performance
- **HTML5 & CSS3** - Modern web standards
- **Font Awesome 6** - Icons and UI elements
- **Tippy.js** - Tooltips and popovers
- **Web Speech API** - Voice command functionality

### Features & APIs
- **Speech Recognition API** - Voice commands
- **Audio API** - Advanced audio controls and synchronization
- **Fetch API** - Modern HTTP requests
- **LocalStorage** - Client-side caching and preferences

## Usage

### Basic Navigation
1. **Select Reciter**: Choose from available reciters using the dropdown
2. **Choose Surah**: Select a chapter from the Surah dropdown
3. **Pick Ayah**: Select a specific verse from the Ayah dropdown
4. **Play Audio**: Use the play/pause button or audio controls

### Advanced Features
- **Theme Toggle**: Use the moon (🌙) icon for dark mode or leaf (🍃) icon for sepia mode
- **Font Selection**: Change Arabic font from the font dropdown
- **Word Meanings**: Click "عرض غريب الكلمات" to show/hide word meanings
- **Voice Commands**: Click "امر صوتي" and speak commands in English
- **Range Selection**: Click "تحديد نطاق" to play multiple consecutive verses
- **Loop Mode**: Enable "تكرار الاية" to repeat the current verse
- **Bookmarks**: Click "علامة مرجعية" to save a verse, or "المرجعيات" to view saved bookmarks

### Keyboard Shortcuts
- **←** (Left Arrow) - Go to previous verse
- **→** (Right Arrow) - Go to next verse

### Voice Commands (English)
- "chapter [number] verse [number]" - Jump to specific verse
- "chapter [number]" - Jump to specific surah
- "verse [number]" - Jump to specific verse in current surah

## Deployment

This project is deployed on Vercel. You can access the live application [here](https://quran-flask-vercel.vercel.app).

### Deployment Configuration
- **Platform**: Vercel
- **Runtime**: Python 3.x
- **Configuration**: `vercel.json` for deployment settings
- **Static Assets**: Served via Vercel's CDN

## Project Structure

```
Quran_Flask/
├── app.py                          # Main Flask application
├── requirements.txt                # Python dependencies
├── vercel.json                    # Vercel deployment configuration
├── README.md                      # Project documentation
├── QUL_data/                      # Quranic data files
│   ├── Digital_Khatt_Aya_Space.json
│   ├── QPC Hafs.json
│   └── word_name.db              # SQLite database
├── static/                        # Static assets
│   ├── script.js                 # Main JavaScript functionality
│   ├── styles.css                # Styling and themes
│   ├── digitalkhatt.woff2        # Arabic font files
│   ├── uthmanic_hafs_v20.ttf
│   └── Naskh-Nastaleeq-IndoPak-QWBW.ttf
└── templates/                     # HTML templates
    └── index.html                # Main application template
```

## License

This project is licensed under the terms of the [LICENSE].

## Contributing

Contributions are welcome! Please fork the repository and create a pull request with your changes.

## Contact

For any inquiries or support, please contact [Ahmed Esawy](https://github.com/AhmedEsawy13).
