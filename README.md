# Dhvani — Hindi PDF se suno tak 🎧

Hindi PDF ya Hinglish text ko **poore, downloadable MP3** mein badalne ka free
personal-use tool. Paid API key nahi chahiye. Default awaaz **local neural
Piper/Priyamvada** hai, taaki cloud service block hone par bhi audio ban sake.

> Is Arena session mein **Dhvani — Hindi PDF to MP3** live preview chal raha hai.
> Usmein PDF upload karein → text review karein → voice sample sunein → **Poora
> MP3 banaiye** → **MP3 download karein**.

## Kya-kya milta hai

- **PDF upload / drag-drop**, ya Hindi-Hinglish text paste.
- **Hindi + English OCR** scanned pages ke liye (`tesserocr`, bina cloud OCR).
- **Editable text review** — OCR ki matra/spelling audio se pehle sudhaar sakte hain.
- **Hinglish preview** — approximate Roman Hindi (`नमस्ते → namaste`). Yeh English
  translation nahi hai; audio reviewed source text se banti hai.
- **Local neural voice**: Priyamvada, female, 22,050 Hz. eSpeak-ng sirf phoneme
  frontend hai; audio classic robotic eSpeak waveform nahi, neural VITS model hai.
- **Optional online natural voices**: Swara (female), Madhur (male), Microsoft
  Edge TTS ke through. Internet aur provider availability chahiye.
- **Speed control** 0.75×–1.5×, voice sample, progress, cancel, retry/resume.
- **Poora text chunk-by-chunk** convert hota hai; koi summary ya 10-minute audio
  cap nahi. Failed chunk ke baad retry completed chunks ko reuse karta hai.
- **MP3 player + download**, text download, browser-session mein job restore.

## Awaaz aur “free” ki saaf baat

| Voice | Mode | Key/cost | Dhyan dein |
|---|---|---|---|
| Priyamvada | Local CPU neural | No API key | Bundled voice ko personal/non-commercial use maana gaya hai; commercial rights verify karein |
| Swara | Online Edge TTS | No API key | Unofficial service; internet, rate limits aur provider terms depend |
| Madhur | Online Edge TTS | No API key | Same online limitations |

Naturalness subjective hai. Pehle **Voice sample suniye** dabakar judge karein.
Local voice human-level quality ki guarantee nahi deta. Mixed Hindi-English PDF
ke liye online Hindi neural voice zyada suitable ho sakti hai; local voice ka
English accent alag ho sakta hai.

Is sandbox ke outbound network mein Microsoft Edge TTS endpoint connect nahi ho
paya tha, isliye default local rakha gaya hai. Local Hindi PDF → OCR → text →
neural audio → MP3 flow yahin test kiya gaya hai. Aapke apne unrestricted network
par online voices chal sakti hain.

## Apne computer par chalayein

Linux / WSL recommended. Python 3.11+ chahiye. System `ffmpeg` ya `tesseract`
install karna zaroori nahi — Python wheels bundled runtime dete hain.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/setup_assets.py     # ~70 MB pinned download, .runtime/ mein
python -m uvicorn dhvani.app:app --host 0.0.0.0 --port 8000
```

Browser mein `http://localhost:8000` kholein. Apne computer par private use ke
liye `--host 127.0.0.1` bhi use kar sakte hain. Arena/live preview mein `0.0.0.0`
zaroori hai.

Setup script sirf `api.github.com` aur `codeload.github.com` se assets leta hai,
checksums verify karta hai, aur remote code execute nahi karta. Models/data Git
mein commit nahi hote.

## Command-line / agent skill

Web app ke bina bhi poora MP3 bana sakte hain:

```bash
.venv/bin/python scripts/pdf_to_mp3.py "/path/book.pdf" \
  -o "/path/book-hindi.mp3" \
  --roman-text "/path/book-hinglish.txt"

# Optional online voice:
.venv/bin/python scripts/pdf_to_mp3.py "/path/book.pdf" \
  --voice hi-IN-SwaraNeural -o "/path/book.mp3"

# Text file bhi supported:
.venv/bin/python scripts/pdf_to_mp3.py "/path/story.txt" -o "/path/story.mp3"
```

Agent workflow [`skills/hindi-pdf-audio/SKILL.md`](skills/hindi-pdf-audio/SKILL.md)
mein hai. Chat mein PDF attach karke “isko Hindi MP3 mein badlo” kehne par agent
isi repo script ka use kar sakta hai. Full-book conversion ke liye chat TTS ki
per-turn clip limits par depend nahi karta.

## Limits

- PDF: **25 MB**, **500 pages** per upload.
- Extracted/reviewed text: **10,00,000 characters**.
- Audio: alag fixed duration cap nahi; lambi book mein time lagega.
- Ek session mein 3 active jobs; server-wide 12 active jobs (default).
- Completed/failed jobs ka cleanup lagbhag **24 ghante** baad; server band ho to
  running job restart par failed mark hoti hai, completed chunks se retry/resume.
  Arena preview ephemeral ho sakta hai — MP3 bante hi download kar lein. Models
  `.runtime/` mein persist hote hain; generated jobs/audio `.cache/dhvani/` mein
  excluded cache hain.
- Bahut badi kitab ko parts mein baantein. Har part ka poora audio milega.

Environment overrides: `DHVANI_MAX_PDF_MB`, `DHVANI_MAX_PAGES`,
`DHVANI_MAX_TEXT_CHARS`, `DHVANI_JOB_TTL_HOURS`, `DHVANI_WORKERS`,
`DHVANI_RUNTIME`, `DHVANI_CACHE`. Public deployment se pehle auth, quotas aur reverse-proxy
limits add karein — yeh single-user/local preview tool hai, hardened public SaaS nahi.

## Privacy

- PDF aur text **server** par process hote hain (Arena mein woh sandbox hai,
  aapka phone/browser nahi).
- **Local mode** mein text kisi third-party TTS service ko nahi bheja jata.
- **Online mode** mein sirf text chunks Microsoft Edge TTS ko jate hain; original
  PDF nahi. Provider logging/terms ke liye unki policy dekhein.
- Browser session token `localStorage` mein hai; jobs usi session se access hoti
  hain. Sensitive/private documents ke liye tool apne private computer par chalayein.
- Koi analytics, account, ya paid API key nahi.

## Troubleshooting

- **Local voice ready nahi**: `python scripts/setup_assets.py`, phir server/page refresh.
- **Online voice connect nahi hui**: firewall/internet ya service limit ho sakti
  hai. Error box mein **Local voice par retry** use karein.
- **Scanned PDF mein text nahi**: OCR checkbox on karein. OCR ke baad text review
  zaroor karein; matra/spelling galat ho sakti hai. Saaf, seedha scan behtar hai.
- **Password-protected PDF**: pehle unlocked copy banayein. Password chat mein share na karein.
- **Audio fail/restart**: Retry dabayein. Completed chunks cache mein hain; poora
  text dobara generate nahi hota.
- **Download button**: MP3 blob browser mein fetch hota hai; download ke liye
  browser ko downloads/pop-ups ki permission deni pad sakti hai.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
node --check dhvani/static/app.js
```

Tests mein Hindi text chunking (no character loss), readable Roman preview,
digital Hindi PDF extraction, scanned Hindi OCR, local neural MP3 round-trip,
chunk resume, online→local fallback, text-edit invalidation, session guards,
sample API aur CLI conversion shamil hain. Network-dependent Edge synthesis ko
tests mein mock kiya gaya hai.

## License / third-party

Application code: **GPL-3.0-or-later** (`LICENSE`). Bundled voice, eSpeak-ng data,
Tesseract data, FFmpeg, PyMuPDF aur dusre dependencies ke apne licenses hain —
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) dekhein. Voice dataset license
sources mein disagreement hai; isliye commercial use se pehle original terms
verify karein. Default bundled voice ko conservative **personal/non-commercial**
use ke liye document kiya gaya hai.
