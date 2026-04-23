import re

with open('static/script.js', 'r') as f:
    js = f.read()

target = r"const ayahText = quranTextData\?\.\[verseKey\]\?\.text \|\| currentAyahData\.text;"
replacement = """const ayahText = (apiSource === 'shamarly' && currentAyahData.words)
                ? currentAyahData.words.map(w => w.text || '').join('')
                : (quranTextData?.[verseKey]?.text || currentAyahData.text);"""

js = re.sub(target, replacement, js)

with open('static/script.js', 'w') as f:
    f.write(js)
