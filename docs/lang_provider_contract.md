# Voice provider + App Language + Content Language: contract (v1)

Goal: each teacher/parent independently chooses **Voice provider** (Gnani default, Sarvam as the second choice) →
**App Language** (UI, 23 options) → **Content Language** (learning content, AI output, speech in/out).
Claude keeps doing all text AI (CLAUDE.md); Sarvam/Gnani do speech only.

Hard rules (all agents):
- **Default behaviour is unchanged.** With content_lang = `hi`, app_lang = `en`/`hi`, provider = `gnani` (falls back to Sarvam),
  every existing endpoint returns what it returns today. All existing tests must still pass.
- Payload changes are additive only. New tables only (create_all cannot alter tables). No new
  frameworks; one new Flutter plugin is allowed (`audioplayers`) for server speech playback.
- Code decides; AI proposes. Machine translation is labelled (`machine_translated: true`) and never
  silently replaces reviewed text in storage.
- Secrets only from env (`SARVAM_API_KEY`, `GNANI_API_KEY`, `ANTHROPIC_API_KEY`); never log them.
- Language codes are ISO 639: `en hi bn mr te ta gu kn ml or pa as ur sa ne kok mai doi sd ks brx mni sat`
  (Odia is `or` internally; providers map it, e.g. Sarvam `od-IN`).

## 1. Language registry — `backend/app/i18n/languages.py` (owner: Backend-Prefs)
```python
@dataclass(frozen=True)
class Language: code: str; name_en: str; name_native: str; script: str; rtl: bool
LANGUAGES: dict[str, Language]          # all 23, insertion order = APP_LANGS order below
APP_LANGS: tuple[str, ...] = ("en","hi","bn","mr","te","ta","gu","kn","ml","or","pa","as","ur",
                              "sa","ne","kok","mai","doi","sd","ks","brx","mni","sat")
def language(code) -> Language          # KeyError for unknown
def prompt_instruction(code) -> str     # e.g. 'Write every learner-facing and classroom text in Marathi (मराठी, Devanagari script). Keep numerals as digits.'
```
`backend/app/i18n/script.py` (owner: Backend-Prefs): `in_script(text, code) -> bool` (letters of the
language's script, ignoring digits/punctuation/spaces; `en` = Latin), `graphemes(text) -> list[str]`
(Brahmic-aware clusters: base + following combining marks (Mn/Mc) + virama-joined consonants; works for
Devanagari, Bengali, Gurmukhi, Gujarati, Odia, Tamil, Telugu, Kannada, Malayalam; falls back to chars).

## 2. Speech providers — `backend/app/speech/` (owner: Backend-Speech)
`capabilities.py`:
```python
PROVIDERS = ("gnani", "sarvam"); DEFAULT_PROVIDER = "gnani"   # unconfigured providers are skipped
SUPPORT = {"sarvam": {"stt": {...23 codes...}, "tts": {"en","hi","bn","gu","kn","ml","mr","or","pa","ta","te"}},
           "gnani":  {"stt": {"en","hi","bn","gu","kn","ml","mr","pa","ta","te"}, "tts": {same 10}}}
def configured(provider) -> bool         # key present
def supports(provider, cap, lang) -> bool   # cap in {"stt","tts"}
def providers_for(cap, lang) -> list[str]   # configured providers supporting it, DEFAULT first
def content_languages() -> list[str]     # APP_LANGS order; langs with >=1 configured provider for BOTH stt and tts;
                                          # if no provider is configured: ["hi","en"] (typing + phone voice)
```
`__init__.py` keeps `get_asr()`, `has_asr()`, `ASRProvider` working (old callers) and adds:
```python
@dataclass class Transcript: text: str; lang: str; provider: str | None; fallback_used: bool; error: str | None
@dataclass class Speech: audio: bytes; mime: str; provider: str
def transcribe(audio, filename, lang="hi", keyterms=None, preferred=None) -> Transcript
def synthesize(text, lang="hi", preferred=None) -> Speech | None
```
Order = preferred first, then the other provider; skip providers not configured or not supporting the
language. Fall back on exception, timeout (STT 25 s, TTS 20 s), HTTP error, or empty/unusable result.
Sarvam STT = `saaras:v3` mode transcribe (replaces deprecated saarika:v2.5); Sarvam TTS = `bulbul:v3`
(speaker that works in all 11 languages). Gnani STT = `POST https://api.vachana.ai/stt/v3`, TTS =
`POST https://api.vachana.ai/api/v1/tts/inference` (header `X-API-Key-ID`), per docs.gnani.ai.
Audio > 30 s: transcribe the first 30 s and say so in `error` (no silent truncation).

`backend/app/api/speech.py` (owner: Backend-Speech) — router, teacher OR parent token:
- `POST /v1/speech/tts` `{text (<=2000 chars), lang}` → `audio/wav` (or provider mime), header
  `X-Speech-Provider`; uses the caller's preferred provider; **204** when no provider can speak it
  (client then uses the phone's voice). Small in-process LRU cache by (lang, provider, text).

## 3. Preferences + languages API (owner: Backend-Prefs)
Table (append to models/tables.py):
```python
class UserPrefs(Base):  __tablename__="user_prefs"; UniqueConstraint("kind","user_id")
    id, kind String(8) ("teacher"|"parent"), user_id Integer, school_id FK,
    voice_provider String(12) default "sarvam", app_lang String(8) default "en",
    content_lang String(8) default "hi", updated_at DateTime
class TranslationCache(Base): __tablename__="translation_cache"; UniqueConstraint("src_lang","tgt_lang","src_hash")
    id, src_lang, tgt_lang String(8), src_hash String(64), src Text, text Text, created_at
```
`backend/app/services/prefs.py`: `get_prefs(db, kind, user_id) -> dict` (defaults if no row; `stored: bool`),
`set_prefs(db, kind, user_id, school_id, **fields)`, `content_lang_for(db, teacher=None, parent=None) -> str`,
`provider_for(db, teacher=None, parent=None) -> str`.
`backend/app/api/prefs.py` router:
- `GET/POST /v1/me/prefs` (teacher), `GET/POST /v1/parent/prefs` (parent):
  body/response `{voice_provider, app_lang, content_lang, stored}`; 422 for app_lang ∉ APP_LANGS,
  content_lang ∉ content_languages(), provider ∉ PROVIDERS.
- `GET /v1/languages` (any valid token): `{app_languages:[{code,name_en,name_native,rtl}],
  content_languages:[{code,name_en,name_native,stt:[providers],tts:[providers]}],
  providers:[{key,name,configured,default}]}`.
`backend/app/i18n/translate.py`: `translate_texts(db, texts, target, source="hi", school_id=None) -> list[dict{text, machine_translated}]`
— identity when target == source; Claude structured call via `llm.py` (batch, keeps numbers/placeholders),
cached in `translation_cache`; on no key/failure returns source text with `machine_translated: False,
untranslated: True`. Never raises.
**Content library pre-translation** (owner: Backend-Prefs): script `backend/scripts/translate_content.py`
writing `content/i18n/<code>/activities.json|probes.json|checkpoint_titles.json|level_check_asks.json`
for the 10 non-Hindi content languages (each entry `machine_translated: true`), plus per-language
reading ladders `content/i18n/<code>/level_check_literacy.json` and voice items generated natively in
that language (not translated), `reviewed: false`. `app/i18n/library.py`: `localized(kind, id, field, lang)`
reading those files, falling back to translate_texts, then to the Hindi source.

## 4. Content language through the workflow
Backend-Classroom (teacher side) — `ai/features.py`, `ai/prompts/{planner,note_extraction,photo_analysis,
roadmap_draft,book_mapping,book_mapping_revise,book_research,voice_assessment,tutor}`, `api/teacher.py`,
`api/books.py`, `api/setup.py`, `services/ledger.py`:
- Every STT call passes the user's content language and preferred provider (`speech.transcribe`).
- Prompts take `{content_language_instruction}`; outputs stay in the existing `*_hi` fields (they mean
  "classroom-language text") and responses gain `content_lang`.
- Plans/probes/activities/level-check asks shown in the content language via `library.localized`
  (with `machine_translated` flag); textbook mapping writes chapter/topic names in the content language.
- `GET /v1/content/titles?lang=<code>` → `{lang, titles:{checkpoint_id: title}, machine_translated}`.
Backend-Voice (learning + parent side) — `ai/voice_tutor.py`, `ai/voice_schemas.py`, `ai/prompts/voice_*`,
`services/voice_session.py`, `voice_types.py`, `voice_bank.py`, `voice_report.py`, `services/tutor.py`,
`services/parent_insights.py`, `speech/scorer.py`, `speech/assess.py`, `api/voice.py`, `api/parent.py`:
- Voice session `lang` accepts every content language (default = parent's content_lang); items: reviewed
  bank for hi/en, else per-language ladder files/generated items; tutor lines, evaluation, narrative and
  report in that language; STT/TTS in that language via `speech.*`; scorer uses `script.graphemes`
  and digit-only numbers for non-Hindi languages.
- Parent summaries/insights: hi/en as today; other content languages via translate_texts (labelled).

## 5. Flutter (both apps)
Flutter-L10n — `lib/l10n.dart` (identical copies), `lib/main.dart` locale/RTL, `assets/i18n/*.json`, fonts,
`tool/` extraction + generation scripts:
- `Lang.code` accepts all 23 codes; `tr(en, hi)` unchanged for en/hi, other codes look up
  `assets/i18n/<code>.json` (key = English string), fallback English. Add `trf(en, hi, args)` with `{name}`
  placeholders. Material locale map: brx/doi/kok/mai/sa/sat→hi, ks/sd→ur, mni→bn; RTL for ur/ks/sd.
- `ContentLang` in l10n.dart: `ValueNotifier<String> code` (default 'hi'), `Map<String,String> titles`,
  `apply(code, titles)`; `cpTitle(map)` prefers `ContentLang.titles[map['checkpoint_id']]` when code ∉ {hi,en}.
- Bundle Noto Sans Ol Chiki + Meetei Mayek (Regular). Generate translation tables for 21 languages
  (machine-translated, placeholder-checked); mark brx doi ks kok mai mni sa sat sd as beta in the picker list.
Flutter-Settings — teacher `screens/settings_screen.dart`, new parent `screens/settings_screen.dart` (+ entry
in parent home app bar), both `lib/tts.dart`, both `lib/api.dart` (prefs load/save), pubspec (audioplayers),
parent `screens/voice_session_screen.dart` (default lang = content language):
- Settings card "Language and voice": Voice service (Sarvam recommended / Gnani, with "not set up yet" when
  unconfigured), App language (searchable list, native names), Content language (from `/v1/languages`),
  one-line plain explanation: "App language = buttons and menus. Learning language = what children read,
  hear and speak."
- On login and app start: `GET prefs` → `Lang.set(app_lang)`, `ContentLang.apply(content_lang, titles from
  /v1/content/titles)`. Changing a setting saves to the server immediately (per user) and locally.
- `Speak.say(text, lang)`: POST `/v1/speech/tts` → play audio; on 204/error use flutter_tts with the
  language's BCP-47 code (e.g. mr-IN).
