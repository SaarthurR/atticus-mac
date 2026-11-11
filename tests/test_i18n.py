"""Translation boundaries and engine locale selection without live asks."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit and Locale checks')
class I18nTests(unittest.TestCase):
    def test_translation_engine_without_a_window(self):
        for name in ('settings', 'onboarding', 'ui'):
            page = (ROOT / 'ui' / (name + '.html')).read_text()
            self.assertIn('/*I18N*/', page)
            self.assertIn("window.i18n?.start(", page)
        script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
global.window = {atticusLanguage:'it',atticusAutoLanguage:'de'};
global.navigator = {language:'en-US'};
global.Node = {TEXT_NODE:3};
let mutate;
global.MutationObserver = class { constructor(callback){mutate=callback} observe(){} disconnect(){} };
function element(text, personal=false, attrs={}) {
  return {childNodes:[{nodeType:3,nodeValue:text}], closest:()=>personal,
    matches:()=>false, hasAttribute:k=>k in attrs, getAttribute:k=>attrs[k], setAttribute:(k,v)=>attrs[k]=v};
}
const label=element('  General  '), dynamic=element('Continue'), personal=element('General',true);
const ask=element('',false,{placeholder:'Ask Atticus…'}), answer=element('General');
let elements=[label,dynamic,personal,ask];
global.document={documentElement:{},body:{},querySelectorAll(selector){
  if(selector==='body,body *') return elements;
  assert(!selector.includes('thread')); return [ask];
}};
const source=fs.readFileSync('ui/i18n.js','utf8');
const maps=JSON.parse(source.split('  const maps = ')[1].split(';\n  let language')[0]);
assert.deepEqual(Object.keys(maps).sort(),['de','es','fr','it']);
for(const map of Object.values(maps)) assert.deepEqual(Object.keys(map).sort(),Object.keys(maps.it).sort());
for(const map of Object.values(maps)) {
  assert(map.Automatic);
  for(const name of ['English','Italiano','Español','Français','Deutsch']) assert.equal(map[name],name);
}
eval(source);
i18n=window.i18n; i18n.start('page');
assert.equal(label.childNodes[0].nodeValue,'  Generale  ');
assert.equal(dynamic.childNodes[0].nodeValue,'Continua');
assert.equal(personal.childNodes[0].nodeValue,'General');
dynamic.childNodes[0].nodeValue='Back'; mutate(); assert.equal(dynamic.childNodes[0].nodeValue,'Indietro');
dynamic.childNodes[0].nodeValue='Unmapped new copy'; mutate(); assert.equal(dynamic.childNodes[0].nodeValue,'Unmapped new copy');
for(const [lang,expected] of [['es','General'],['fr','Général'],['de','Allgemein'],['en','General'],['it','Generale']]) {
  i18n.setLanguage(lang); assert.equal(label.childNodes[0].nodeValue,`  ${expected}  `);
}
i18n.setLanguage('auto'); assert.equal(label.childNodes[0].nodeValue,'  Allgemein  ');
i18n.setLanguage('it'); elements.push(answer); i18n.start('labels');
assert.equal(ask.getAttribute('placeholder'),'Chiedi ad Atticus…');
assert.equal(answer.childNodes[0].nodeValue,'General');
i18n.setLanguage('de'); assert.equal(answer.childNodes[0].nodeValue,'General');
console.log('translation engine passed');
"""
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('translation engine passed', result.stdout)

    def test_automatic_speech_stays_english_and_wake_word_is_unchanged(self):
        swift = (ROOT / 'Atticus.swift').read_text()
        helper = swift[swift.index('func supportedSpeechLocale('):swift.index('\nfunc applySharing')]
        self.assertIn('language: String = Prefs.str("uiLanguage") == "auto" ? "en" : Prefs.uiLanguage', helper)
        prepare = swift[swift.index('    func prepareSpeech()'):swift.index('    var text =')]
        self.assertIn('let choice = Prefs.str("uiLanguage")', prepare)
        self.assertIn('let language = choice == "auto" ? "en" : Prefs.uiLanguage', prepare)
        self.assertIn('supportedSpeechLocale(locales, language: language)', prepare)
        self.assertIn('if choice != Prefs.str("uiLanguage")', prepare)
        self.assertEqual(swift.count('SFSpeechRecognizer(locale: Locale(identifier: "en-US"))'), 2)

    def test_speech_uses_exact_engine_locale_or_english(self):
        swift = (ROOT / 'Atticus.swift').read_text()
        helper = swift[swift.index('func supportedSpeechLocale('):swift.index('\nfunc applySharing')]
        resolver = swift[swift.index('    static func resolveUILanguage('):swift.index('    static func num(')]
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        source = Path(temp.name) / 'locales.swift'
        source.write_text('import Foundation\nenum Prefs { static var uiLanguage = "en"; static var choice = "auto"; static func str(_ key: String) -> String { choice }\n' + resolver + '}\n' + helper + '''
for code in ["it", "es", "fr", "de"] {
    let exact = Locale(identifier: code + "-CH")
    Prefs.uiLanguage = code; Prefs.choice = "auto"
    precondition(supportedSpeechLocale([exact]).identifier == "en-US")
    Prefs.choice = code
    precondition(supportedSpeechLocale([exact]) == exact)
    precondition(supportedSpeechLocale([]).identifier == "en-US")
    precondition(supportedSpeechLocale([Locale(identifier:"en-US"), exact], language:code) == exact)
    precondition(supportedSpeechLocale([Locale(identifier:"en-US")], language:code).identifier == "en-US")
    precondition(Prefs.resolveUILanguage(code + "-CH") == code)
}
precondition(supportedSpeechLocale([Locale(identifier:"en-GB")], language:"en").identifier == "en-US")
precondition(supportedSpeechLocale([], language:"it").identifier == "en-US")
precondition(Prefs.resolveUILanguage("zh-Hans") == "en")
print("locale selection passed")
''')
        result = subprocess.run(['swift', str(source)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('locale selection passed', result.stdout)
