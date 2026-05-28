

const _cache = {};
let _current = {};
let _lang = 'en';


function _detectLang() {
    const nav = navigator.language || navigator.userLanguage || 'en';
    const base = nav.split('-')[0].toLowerCase();
    return ['en', 'zh'].includes(base) ? base : 'en';
}


async function _load(lang) {
    if (_cache[lang]) return _cache[lang];
    try {
        const res = await fetch(`./locales/${lang}.json`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        _cache[lang] = await res.json();
    } catch (e) {
        console.warn(`i18n: failed to load locale "${lang}"`, e);
        _cache[lang] = {};
    }
    return _cache[lang];
}


export function t(key, params) {
    let str = _current[key] ?? key;
    if (params) {
        for (const [k, v] of Object.entries(params)) {
            str = str.replace(new RegExp(`\\{${k}\\}`, 'g'), v);
        }
    }
    return str;
}


export function applyTranslations() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        if (key) el.textContent = t(key);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        const key = el.getAttribute('data-i18n-placeholder');
        if (key) el.placeholder = t(key);
    });
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
        const key = el.getAttribute('data-i18n-title');
        if (key) el.title = t(key);
    });
    
    document.documentElement.lang = _lang;
}


export async function setLanguage(lang) {
    _lang = lang;
    _current = await _load(lang);
    applyTranslations();
}


export function getCurrentLang() {
    return _lang;
}


export async function initI18n(savedLang) {
    _lang = savedLang || _detectLang();
    _current = await _load(_lang);
    applyTranslations();
}
