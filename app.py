from flask import Flask, jsonify, render_template, request, g, Response, redirect
import json
import sqlite3
import os
import logging
import requests
from functools import lru_cache
from flask import make_response
import gzip
from io import BytesIO

app = Flask(__name__, static_folder='static')

# Enable response compression
app.config['COMPRESS_MIMETYPES'] = ['text/html', 'text/css', 'application/json', 'application/javascript']
app.config['COMPRESS_LEVEL'] = 6
app.config['COMPRESS_MIN_SIZE'] = 500

# Configure logging
if not app.debug:
    logging.basicConfig(level=logging.INFO)
    app.logger.setLevel(logging.INFO)

# Compression and security improvements
@app.after_request
def after_request(response):
    """Add security headers and compression to all responses"""
    # Security headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://unpkg.com https://cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' https://unpkg.com https://cdnjs.cloudflare.com; font-src 'self' https://cdnjs.cloudflare.com; media-src 'self' https://audio.qurancdn.com; connect-src 'self';"
    
    # Cache control for API responses (cache for 1 hour)
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'public, max-age=3600'
    
    # GZIP compression for JSON responses - check early to avoid unnecessary processing
    if (response.status_code == 200 and 
        response.content_type and 'application/json' in response.content_type and
        'gzip' in request.headers.get('Accept-Encoding', '').lower()):
        
        response_data = response.get_data()
        # Only compress if response is large enough
        if len(response_data) > 500:
            gzip_buffer = BytesIO()
            with gzip.GzipFile(mode='wb', fileobj=gzip_buffer, compresslevel=6) as gzip_file:
                gzip_file.write(response_data)
            
            response.set_data(gzip_buffer.getvalue())
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Content-Length'] = len(response.get_data())
            response.headers['Vary'] = 'Accept-Encoding'
    
    return response

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Resource not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"Internal server error: {error}")
    return jsonify({"error": "Internal server error"}), 500

DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'QUL_data', 'word_name.db')

# Load Quranic text data with error handling
try:
    with open('QUL_data/Digital_Khatt_Aya_Space.json', 'r', encoding='utf-8') as f:
        digital_khatt_data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    app.logger.error(f"Error loading Digital_Khatt_Aya_Space.json: {e}")
    digital_khatt_data = {}

try:
    with open('QUL_data/QPC Hafs.json', 'r', encoding='utf-8') as f:
        qpc_hafs_data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    app.logger.error(f"Error loading QPC Hafs.json: {e}")
    qpc_hafs_data = {}

try:
    with open('QUL_data/Indopak Nastaleeq_Waqf.json', 'r', encoding='utf-8') as f:
        indopak_nastaleeq_data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    app.logger.error(f"Error loading Indopak Nastaleeq_Waqf.json: {e}")
    indopak_nastaleeq_data = {}

# Load transliteration data with error handling
try:
    with open('QUL_data/Transliteration.json', 'r', encoding='utf-8') as f:
        transliteration_data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    app.logger.error(f"Error loading Transliteration.json: {e}")
    transliteration_data = {}

# Load surah names data (local file to avoid external API dependency)
try:
    with open('QUL_data/surahs.json', 'r', encoding='utf-8') as f:
        surahs_data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    app.logger.error(f"Error loading surahs.json: {e}")
    surahs_data = []

# Lazy loading for tafseer data (only load when needed)
tafseer_files = {
    'تفسير السعدي': 'QUL_data/Tafseer Al Saddi.json',
    'تفسير القرطبي': 'QUL_data/Tafseer Al Qurtubi.json',
    'تفسير البغوي': 'QUL_data/Tafseer Al-Baghawi.json'
}

@lru_cache(maxsize=3)
def load_tafseer_data(tafseer_name):
    """Lazy load tafseer data with caching via @lru_cache"""
    tafseer_file = tafseer_files.get(tafseer_name)
    if not tafseer_file:
        return {}
    
    try:
        with open(tafseer_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data
    except (FileNotFoundError, json.JSONDecodeError) as e:
        app.logger.error(f"Error loading {tafseer_file}: {e}")
        return {}


# Load audio data for different reciters with error handling
reciters = {
    "AbdulBaset AbdulSamad": "QUL_data/AbdulBaset AbdulSamad Recitation.json",
    "Mohamed al-Tablawi": "QUL_data/Mohamed al-Tablawi Recitation.json",
    "Mohamed al-Minshawi": "QUL_data/Mohamed Siddiq al-Minshawi Recitation.json",
}

audio_data = {}
for reciter, file_name in reciters.items():
    try:
        with open(file_name, 'r', encoding='utf-8') as f:
            audio_data[reciter] = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        app.logger.error(f"Error loading {file_name}: {e}")
        audio_data[reciter] = []

# Function to create the mapping for list-based audio data
def create_mapping_from_list(quran_text_data, audio_data):
    if not quran_text_data or not audio_data:
        app.logger.warning("Empty quran_text_data or audio_data provided")
        return {}
        
    id_to_verse_key = {data['id']: verse_key for verse_key, data in quran_text_data.items() if isinstance(data, dict) and 'id' in data}
    verse_key_to_segment_map = {}

    for audio_info in audio_data:
        if not isinstance(audio_info, dict):
            app.logger.warning(f"Unexpected non-dict entry in audio data: {audio_info}")
            continue

        ayah_number = audio_info.get('ayah_number')
        audio_url = audio_info.get('audio_url')
        segments = audio_info.get('segments')

        if not (ayah_number and audio_url):
            app.logger.warning(f"Incomplete audio info (missing ayah_number or audio_url): {audio_info}")
            continue
            
        if segments is None:
            app.logger.warning(f"Missing segments for ayah {ayah_number}")
            continue

        verse_key = id_to_verse_key.get(ayah_number)

        if verse_key:
            verse_info = quran_text_data.get(verse_key, {})
            verse_key_to_segment_map[verse_key] = {
                'id': verse_info.get('id', ayah_number),
                'surah_number': int(verse_key.split(':')[0]),
                'ayah_number': int(verse_key.split(':')[1]),
                'audio_url': audio_url,
                'segments': [
                    {
                        'start_word_index': segment[0],
                        'end_word_index': segment[1],
                        'start_time': segment[2],
                        'end_time': segment[3]
                    }
                    for segment in segments if isinstance(segment, (list, tuple)) and len(segment) >= 4
                ]
            }
        else:
            app.logger.warning(f"Ayah number {ayah_number} not found in Quranic text data")

    return verse_key_to_segment_map

# Function to create the mapping for dict-based audio data
def create_mapping_from_dict(quran_text_data, audio_data):
    if not quran_text_data or not audio_data:
        app.logger.warning("Empty quran_text_data or audio_data provided")
        return {}
        
    id_to_verse_key = {data['id']: verse_key for verse_key, data in quran_text_data.items() if isinstance(data, dict) and 'id' in data}
    verse_key_to_segment_map = {}

    for verse_key, audio_info in audio_data.items():
        if not isinstance(audio_info, dict):
            app.logger.warning(f"Unexpected non-dict entry in audio data: {audio_info}")
            continue

        ayah_number = audio_info.get('ayah_number')
        audio_url = audio_info.get('audio_url')
        segments = audio_info.get('segments')

        if not (ayah_number and audio_url):
            app.logger.warning(f"Incomplete audio info (missing ayah_number or audio_url): {audio_info}")
            continue
            
        if segments is None:
            app.logger.warning(f"Missing segments for ayah {ayah_number}")
            continue

        verse_key_db = id_to_verse_key.get(ayah_number)

        if verse_key_db:
            verse_info = quran_text_data.get(verse_key_db, {})
            verse_key_to_segment_map[verse_key_db] = {
                'id': verse_info.get('id', ayah_number),
                'surah_number': int(verse_key_db.split(':')[0]),
                'ayah_number': int(verse_key_db.split(':')[1]),
                'audio_url': audio_url,
                'segments': [
                    {
                        'start_word_index': segment[0],
                        'end_word_index': segment[1],
                        'start_time': segment[2],
                        'end_time': segment[3]
                    }
                    for segment in segments if isinstance(segment, (list, tuple)) and len(segment) >= 4
                ]
            }
        else:
            app.logger.warning(f"Ayah number {ayah_number} not found in Quranic text data")

    return verse_key_to_segment_map

# Create mappings for each reciter with improved error handling
reciter_mappings = {}
for reciter, data in audio_data.items():
    try:
        if isinstance(data, list):
            reciter_mappings[reciter] = create_mapping_from_list(digital_khatt_data, data)
        elif isinstance(data, dict):
            reciter_mappings[reciter] = create_mapping_from_dict(digital_khatt_data, data)
        else:
            app.logger.warning(f"Unexpected data structure for reciter {reciter}: {type(data)}")
            reciter_mappings[reciter] = {}
    except Exception as e:
        app.logger.error(f"Error creating mapping for reciter {reciter}: {e}")
        reciter_mappings[reciter] = {}


# Database helper functions
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        # Check if database file exists
        if not os.path.exists(DATABASE):
            app.logger.error(f"Database file not found: {DATABASE}")
            return None
            
        try:
            db = g._database = sqlite3.connect(DATABASE)
            db.row_factory = sqlite3.Row  # To access columns by name
        except sqlite3.Error as e:
            app.logger.error(f"Database connection error: {e}")
            return None
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def get_word_meanings(surah_number, ayah_number):
    db = get_db()
    if db is None:
        app.logger.warning("Database not available for word meanings")
        return {}
    
    try:
        cursor = db.cursor()
        query = '''
            SELECT word, meaning
            FROM verses
            WHERE surah_number = ? AND ayah_number = ?
        '''
        cursor.execute(query, (surah_number, ayah_number))
        rows = cursor.fetchall()
        word_meanings = {}
        for row in rows:
            word_meanings[row['word']] = row['meaning']
        return word_meanings
    except sqlite3.Error as e:
        app.logger.error(f"Database query error: {e}")
        return {}

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    health_status = {
        "status": "healthy",
        "service": "Quran Flask API",
        "checks": {
            "database": os.path.exists(DATABASE),
            "digital_khatt_loaded": bool(digital_khatt_data),
            "qpc_hafs_loaded": bool(qpc_hafs_data),
            "indopak_loaded": bool(indopak_nastaleeq_data),
            "transliteration_loaded": bool(transliteration_data),
            "audio_data_loaded": bool(audio_data)
        }
    }
    
    # Check if any critical component is missing
    if not all([
        digital_khatt_data,
        qpc_hafs_data,
        indopak_nastaleeq_data,
        transliteration_data
    ]):
        health_status["status"] = "degraded"
        return jsonify(health_status), 503
    
    return jsonify(health_status), 200

@app.route('/api/surahs', methods=['GET'])
def get_surahs():
    """Get list of surahs with their names (local data, no external API dependency)"""
    if surahs_data:
        return jsonify(surahs_data)
    
    # Fallback to extracting surah numbers from text data
    quran_text_data = get_quran_text_data()
    surahs = []
    for verse_key in quran_text_data.keys():
        surah_number = int(verse_key.split(':')[0])
        if surah_number not in surahs:
            surahs.append(surah_number)
    surahs.sort()
    return jsonify(surahs)

@app.route('/api/surahs/<int:surah_number>/ayahs', methods=['GET'])
def get_ayahs(surah_number):
    # Validate surah number range (1-114)
    if not (1 <= surah_number <= 114):
        return jsonify({"error": "Invalid surah number. Must be between 1 and 114."}), 400
        
    quran_text_data = get_quran_text_data()
    ayahs = []
    for verse_key in quran_text_data.keys():
        if verse_key.startswith(f"{surah_number}:"):
            ayah_number = int(verse_key.split(':')[1])
            if ayah_number not in ayahs:
                ayahs.append(ayah_number)
    ayahs.sort()
    return jsonify(ayahs)

@app.route('/api/surahs/<int:surah_number>/ayahs/<int:ayah_number>', methods=['GET'])
def get_ayah_text(surah_number, ayah_number):
    # Validate surah number range (1-114)
    if not (1 <= surah_number <= 114):
        return jsonify({"error": "Invalid surah number. Must be between 1 and 114."}), 400
    
    # Validate ayah number (basic range check)
    if ayah_number < 1 or ayah_number > 286:  # Max ayah in any surah
        return jsonify({"error": "Invalid ayah number."}), 400
        
    quran_text_data = get_quran_text_data()

    # Removed surah name mapping
    verse_key = f"{surah_number}:{ayah_number}"
    if verse_key in quran_text_data:
        ayah_data = quran_text_data[verse_key]
        ayah_data['id'] = ayah_number  # Add ID to the Ayah data
        ayah_data['transliteration'] = transliteration_data.get(verse_key, {})
        
        # Lazy load tafseers - only load when requested
        ayah_data['tafseer'] = {}
        for tafseer_name in tafseer_files.keys():
            tafseer_data_loaded = load_tafseer_data(tafseer_name)
            ayah_data['tafseer'][tafseer_name] = tafseer_data_loaded.get(verse_key, {})
        
        # Add reciters' audio information
        ayah_data['reciters'] = {}
        for reciter, mapping in reciter_mappings.items():
            if verse_key in mapping:
                ayah_data['reciters'][reciter] = mapping[verse_key]
        
        # Fetch word meanings from the SQLite database
        word_meanings = get_word_meanings(surah_number, ayah_number)
        ayah_data['word_meanings'] = word_meanings  # Add meanings to the response
        
        return jsonify(ayah_data)
    return jsonify({"error": "Ayah not found"}), 404

@app.route('/api/reciters/<reciter>/ayahs/<int:ayah_number>/audio', methods=['GET'])
def get_audio_segments(reciter, ayah_number):
    # Validate ayah number
    if ayah_number < 1:
        return jsonify({"error": "Invalid ayah number."}), 400
    
    if reciter in reciter_mappings:
        # Find the verse key using the global Ayah number
        verse_key = next((key for key, value in reciter_mappings[reciter].items() if value['id'] == ayah_number), None)
        if not verse_key:
            return jsonify({"error": "Verse key not found"}), 404

        audio_info = reciter_mappings[reciter].get(verse_key)
        if audio_info:
            return jsonify(audio_info)
    return jsonify({"error": "Audio not found"}), 404

@app.route('/api/quran-text', methods=['GET'])
def get_quran_text():
    quran_text_data = get_quran_text_data()
    return jsonify(quran_text_data)

@app.route('/api/transliteration', methods=['GET'])
def get_transliteration():
    return jsonify(transliteration_data)

@app.route('/api/tafseer', methods=['GET'])
def get_tafseer():
    """Get tafseer data - deprecated, use /api/tafseer/<name> instead"""
    # Return empty for now to avoid loading all tafseers at once
    return jsonify({
        "message": "Use /api/tafseer/<tafseer_name> to get specific tafseer",
        "available_tafseers": list(tafseer_files.keys())
    })

@app.route('/api/tafseer/<tafseer_name>', methods=['GET'])
def get_specific_tafseer(tafseer_name):
    """Get specific tafseer data with lazy loading"""
    if tafseer_name not in tafseer_files:
        return jsonify({
            "error": "Invalid tafseer name",
            "available_tafseers": list(tafseer_files.keys())
        }), 404
    
    tafseer_data_loaded = load_tafseer_data(tafseer_name)
    return jsonify(tafseer_data_loaded)

@app.route('/')
def index():
    return render_template('index.html')

def get_quran_text_data():
    source = request.args.get('source', 'qpc_hafs')
    # Validate source parameter
    valid_sources = ['digital_khatt', 'indopak_nastaleeq', 'qpc_hafs']
    if source not in valid_sources:
        source = 'qpc_hafs'  # Default fallback
        
    if source == 'digital_khatt':
        return digital_khatt_data
    elif source == 'indopak_nastaleeq':
        return indopak_nastaleeq_data
    return qpc_hafs_data

@app.route('/api/audio-proxy')
def audio_proxy():
    """Validate and redirect to audio files to avoid firewall issues in sandbox environments"""
    from urllib.parse import urlparse
    
    audio_url = request.args.get('url')
    if not audio_url:
        return jsonify({"error": "Missing audio URL"}), 400
    
    # Parse and validate the URL
    try:
        parsed_url = urlparse(audio_url)
        
        # Only allow HTTPS protocol
        if parsed_url.scheme != 'https':
            return jsonify({"error": "Only HTTPS URLs are allowed"}), 400
        
        # Only allow specific trusted domain (without port)
        allowed_domain = 'audio.qurancdn.com'
        # parsed_url.netloc includes the port if specified
        # We want to allow only the domain without any explicit port
        # or with the default HTTPS port (443)
        if parsed_url.netloc != allowed_domain:
            # Check if it's the domain with explicit :443
            if not (parsed_url.hostname == allowed_domain and parsed_url.port in (None, 443)):
                return jsonify({"error": f"Only {allowed_domain} domain is allowed"}), 400
            
    except Exception as e:
        app.logger.error(f"URL validation error: {e}")
        return jsonify({"error": "Invalid URL format"}), 400
    
    # Redirect to the validated audio URL instead of proxying
    # This allows the client browser to fetch directly from audio.qurancdn.com
    # which is allowed by the CSP media-src directive and avoids firewall issues
    # Using 307 (Temporary Redirect) to preserve request method
    return redirect(audio_url, code=307)

@app.route('/api/search', methods=['GET'])
def search_verses():
    """Search for verses containing specific text or words"""
    query = request.args.get('q', '').strip()
    source = request.args.get('source', 'qpc_hafs')
    limit = request.args.get('limit', 50, type=int)
    
    if not query:
        return jsonify({"error": "Search query parameter 'q' is required"}), 400
    
    if len(query) > 500:
        return jsonify({"error": "Search query too long. Maximum 500 characters allowed."}), 400
    
    if limit < 1 or limit > 100:
        limit = 50
    
    # Validate source parameter
    valid_sources = ['digital_khatt', 'indopak_nastaleeq', 'qpc_hafs']
    if source not in valid_sources:
        source = 'qpc_hafs'
    
    # Get appropriate data source
    if source == 'digital_khatt':
        search_data = digital_khatt_data
    elif source == 'indopak_nastaleeq':
        search_data = indopak_nastaleeq_data
    else:
        search_data = qpc_hafs_data
    
    # Search through verses
    results = []
    
    for verse_key, verse_data in search_data.items():
        if len(results) >= limit:
            break
            
        # Search in Arabic text (exact match in the text)
        text = verse_data.get('text', '')
        if query in text:
            surah_num, ayah_num = verse_key.split(':')
            results.append({
                'verse_key': verse_key,
                'surah_number': int(surah_num),
                'ayah_number': int(ayah_num),
                'text': text,
                'highlight': True
            })
    
    return jsonify({
        'query': query,
        'total_results': len(results),
        'results': results,
        'source': source
    })

@app.route('/api/word-search', methods=['GET'])
def search_word_meanings():
    """Search for word meanings in the database"""
    query = request.args.get('q', '').strip()
    limit = request.args.get('limit', 50, type=int)
    
    if not query:
        return jsonify({"error": "Search query parameter 'q' is required"}), 400
    
    if len(query) > 500:
        return jsonify({"error": "Search query too long. Maximum 500 characters allowed."}), 400
    
    if limit < 1 or limit > 100:
        limit = 50
    
    db = get_db()
    if db is None:
        return jsonify({"error": "Database not available"}), 503
    
    try:
        cursor = db.cursor()
        # Search in both word and meaning columns
        search_query = '''
            SELECT DISTINCT surah_number, ayah_number, word, meaning
            FROM verses
            WHERE word LIKE ? OR meaning LIKE ?
            LIMIT ?
        '''
        search_pattern = f'%{query}%'
        cursor.execute(search_query, (search_pattern, search_pattern, limit))
        rows = cursor.fetchall()
        
        results = []
        for row in rows:
            results.append({
                'surah_number': row['surah_number'],
                'ayah_number': row['ayah_number'],
                'word': row['word'],
                'meaning': row['meaning']
            })
        
        return jsonify({
            'query': query,
            'total_results': len(results),
            'results': results
        })
    except sqlite3.Error as e:
        app.logger.error(f"Database search error: {e}")
        return jsonify({"error": "Search failed"}), 500

if __name__ == '__main__':
    app.run(debug=True)
