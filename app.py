from flask import Flask, jsonify, render_template, request
import json

app = Flask(__name__, static_folder='static')

# Load Quranic text data
with open('QUL_data/Digital_Khatt_Aya_Space.json', 'r', encoding='utf-8') as f:
    digital_khatt_data = json.load(f)

with open('QUL_data/QPC Hafs.json', 'r', encoding='utf-8') as f:
    qpc_hafs_data = json.load(f)

# Load transliteration and tafseer data
with open('QUL_data/Transliteration.json', 'r', encoding='utf-8') as f:
    transliteration_data = json.load(f)

# Load multiple tafseer data files
tafseer_files = {
    'تفسير السعدي': 'QUL_data/Tafseer Al Saddi.json',
    'تفسير القرطبي': 'QUL_data/Tafseer Al Qurtubi.json',
    'تفسير البغوي': 'QUL_data/Tafseer Al-Baghawi.json'
}

tafseer_data = {}
for tafseer_name, tafseer_file in tafseer_files.items():
    with open(tafseer_file, 'r', encoding='utf-8') as f:
        tafseer_data[tafseer_name] = json.load(f)


# Load audio data for different reciters
reciters = {
    "AbdulBaset AbdulSamad": "QUL_data/AbdulBaset AbdulSamad Recitation.json",
    "Mohamed al-Tablawi": "QUL_data/Mohamed al-Tablawi Recitation.json",
    "Mohamed al-Minshawi": "QUL_data/Mohamed Siddiq al-Minshawi Recitation.json",
}

audio_data = {}
for reciter, file_name in reciters.items():
    with open(file_name, 'r', encoding='utf-8') as f:
        audio_data[reciter] = json.load(f)

# Function to create the mapping for list-based audio data
def create_mapping_from_list(quran_text_data, audio_data):
    id_to_verse_key = {data['id']: verse_key for verse_key, data in quran_text_data.items()}
    verse_key_to_segment_map = {}

    for audio_info in audio_data:
        if not isinstance(audio_info, dict):
            print(f"Warning: Unexpected non-dict entry in audio data: {audio_info}")
            continue

        ayah_number = audio_info.get('ayah_number')
        audio_url = audio_info.get('audio_url')
        segments = audio_info.get('segments')

        if not (ayah_number and audio_url and segments):
            print(f"Warning: Incomplete audio info: {audio_info}")
            continue

        verse_key = id_to_verse_key.get(ayah_number)

        if verse_key:
            verse_info = quran_text_data[verse_key]
            verse_key_to_segment_map[verse_key] = {
                'id': verse_info['id'],
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
                    for segment in segments
                ]
            }
        else:
            print(f"Warning: Ayah number {ayah_number} not found in Quranic text data")

    return verse_key_to_segment_map

# Function to create the mapping for dict-based audio data
def create_mapping_from_dict(quran_text_data, audio_data):
    id_to_verse_key = {data['id']: verse_key for verse_key, data in quran_text_data.items()}
    verse_key_to_segment_map = {}

    for verse_key, audio_info in audio_data.items():
        if not isinstance(audio_info, dict):
            print(f"Warning: Unexpected non-dict entry in audio data: {audio_info}")
            continue

        ayah_number = audio_info.get('ayah_number')
        audio_url = audio_info.get('audio_url')
        segments = audio_info.get('segments')

        if not (ayah_number and audio_url and segments):
            print(f"Warning: Incomplete audio info: {audio_info}")
            continue

        verse_key = id_to_verse_key.get(ayah_number)

        if verse_key:
            verse_info = quran_text_data[verse_key]
            verse_key_to_segment_map[verse_key] = {
                'id': verse_info['id'],
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
                    for segment in segments
                ]
            }
        else:
            print(f"Warning: Ayah number {ayah_number} not found in Quranic text data")

    return verse_key_to_segment_map

# Create mappings for each reciter
reciter_mappings = {}
for reciter, data in audio_data.items():
    if isinstance(data, list):
        reciter_mappings[reciter] = create_mapping_from_list(digital_khatt_data, data)
    elif isinstance(data, dict):
        reciter_mappings[reciter] = create_mapping_from_dict(digital_khatt_data, data)
    else:
        print(f"Warning: Unexpected data structure for reciter {reciter}")

@app.route('/api/surahs', methods=['GET'])
def get_surahs():
    quran_text_data = get_quran_text_data()
    surahs = []
    for verse_key in quran_text_data.keys():
        surah_number = verse_key.split(':')[0]
        if surah_number not in surahs:
            surahs.append(surah_number)
    return jsonify(surahs)

@app.route('/api/surahs/<int:surah_number>/ayahs', methods=['GET'])
def get_ayahs(surah_number):
    quran_text_data = get_quran_text_data()
    ayahs = []
    for verse_key in quran_text_data.keys():
        if verse_key.startswith(f"{surah_number}:"):
            ayah_number = verse_key.split(':')[1]
            if ayah_number not in ayahs:
                ayahs.append(ayah_number)
    return jsonify(ayahs)

@app.route('/api/surahs/<int:surah_number>/ayahs/<int:ayah_number>', methods=['GET'])
def get_ayah_text(surah_number, ayah_number):
    quran_text_data = get_quran_text_data()
    verse_key = f"{surah_number}:{ayah_number}"
    if verse_key in quran_text_data:
        ayah_data = quran_text_data[verse_key]
        ayah_data['id'] = ayah_number  # Add ID to the Ayah data
        ayah_data['transliteration'] = transliteration_data.get(verse_key, {})
        
        # Add all tafseers
        ayah_data['tafseer'] = {tafseer_file: tafseer_data.get(tafseer_file, {}).get(verse_key, {}) for tafseer_file in tafseer_files}
        
        # Add reciters' audio information
        ayah_data['reciters'] = {}
        for reciter, mapping in reciter_mappings.items():
            if verse_key in mapping:
                ayah_data['reciters'][reciter] = mapping[verse_key]
        
        return jsonify(ayah_data)
    return jsonify({"error": "Ayah not found"}), 404

@app.route('/api/reciters/<reciter>/ayahs/<int:ayah_number>/audio', methods=['GET'])
def get_audio_segments(reciter, ayah_number):
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
    return jsonify(tafseer_data)

@app.route('/')
def index():
    return render_template('index.html')

def get_quran_text_data():
    source = request.args.get('source','qpc_hafs')
    if source == 'digital_khatt':
        return  digital_khatt_data
    return qpc_hafs_data

if __name__ == '__main__':
    app.run(debug=True)
