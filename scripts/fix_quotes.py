import re

with open('static/script.js', 'r') as f:
    js = f.read()

# add quotes back but exactly as single quotes
js = js.replace("document.body.style.setProperty('--shamarly-font', fontName);", "document.body.style.setProperty('--shamarly-font', `'${fontName}'`);")

with open('static/script.js', 'w') as f:
    f.write(js)
