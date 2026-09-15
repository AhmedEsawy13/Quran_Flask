'use strict';
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '../../static/js/athar_phoneme_dtw.js'), 'utf8');
eval(src);
const { matchWord, createSequencer } = global.AtharPhonemeDtw;

function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}

const exact = matchWord('بِسمِ', 'بِسمِ');
assert(exact && exact.tokensConsumed === 5, 'exact match consumes the word');
assert(exact.pathCost === 0, 'exact match cost is 0');

const madd = matchWord('ررَحِۦۦۦۦم', 'ررَحِۦۦم');
assert(madd && madd.tokensConsumed === 'ررَحِۦۦۦۦم'.length, 'trailing madd vowels are consumed (1.0.2 endpoint)');

const twice = matchWord('للَااهِررَحمَاانِللَااهِ', 'للَااهِ');
assert(twice && twice.tokensConsumed === 'للَااهِ'.length, 'first لله is not stretched to the next لله');

const shaddah = matchWord('ررَبِّ', 'ررَبِّ');
assert(shaddah && shaddah.tokensConsumed > 0, 'short shaddah word matches');

const seq = createSequencer(
    [
        { ph: 'بِسمِ', ayah: 1, wpos: 0 },
        { ph: 'للَااهِ', ayah: 1, wpos: 1 },
        { ph: 'ررَحمَاانِ', ayah: 1, wpos: 2 },
    ],
    { maxSkipWords: 1, commits: [] },
);
const commits = [];
const seq2 = createSequencer(
    [
        { ph: 'بِسمِ', ayah: 1, wpos: 0 },
        { ph: 'للَااهِ', ayah: 1, wpos: 1 },
        { ph: 'ررَحمَاانِ', ayah: 1, wpos: 2 },
    ],
    { maxSkipWords: 1, onCommit: (kind, entry) => commits.push([kind, entry.wpos]) },
);
seq2.process('للَااهِ');
assert(commits.some(c => c[0] === 'red' && c[1] === 0), 'skip of one word is red, not a 5-word jump');
assert(commits.some(c => c[0] === 'green' && c[1] === 1), 'lookahead word is green');

const pause = createSequencer(
    [{ ph: 'هُوَ', ayah: 2, wpos: 4 }],
    { maxSkipWords: 1, onCommit: (kind, entry) => commits.push(['silence', kind, entry.wpos]) },
);
pause.process('هُ');
const sealed = pause.onSilence();
assert(sealed && sealed.wpos === 4, 'silence commits the current word (waqf/sukoon), does not skip');

console.log('ok  athar phoneme DTW matches ReciteQuran 1.0.2 endpoint + waqf silence');
