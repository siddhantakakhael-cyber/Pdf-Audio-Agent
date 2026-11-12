---
name: hindi-pdf-audio
description: Hindi PDF ya Hinglish text ko poore downloadable MP3 mein convert karna. Free local neural voice default; optional online natural Hindi voices; scanned PDFs ke liye Hindi+English OCR.
---

# Hindi PDF → Audio skill

## Kab use karein
User PDF attach karke kahe “isko audio/MP3 mein badlo”, “Hindi mein sunao”, ya “Hinglish audiobook chahiye”. Summary nahi banani hai unless user explicitly maange.

## Workflow
1. Attached PDF ka actual workspace path lo. Filename/extension verify karo; path invent mat karo.
2. Repo root mein dependencies aur assets ready hon to yahin chalao:
   ```bash
   .venv/bin/python scripts/pdf_to_mp3.py "/actual/path/book.pdf" -o "/actual/path/book-hindi.mp3" --roman-text "/actual/path/book-hinglish.txt"
   ```
   Pehli baar setup:
   ```bash
   python -m venv .venv
   .venv/bin/pip install -r requirements.txt
   .venv/bin/python scripts/setup_assets.py
   ```
3. Default voice `priyamvada` local neural hai, bina API key. Online natural voices ke liye `--voice hi-IN-SwaraNeural` ya `--voice hi-IN-MadhurNeural`; internet/firewall allow hona chahiye. Sandbox mein Edge endpoint blocked ho sakta hai—fail ho to local voice par retry karo aur user ko batao.
4. Script stderr/error par silently partial MP3 deliver mat karo. Completed chunks `.cache/dhvani/cli/<hash>/` mein cache hain; same command retry se resume hota hai.
5. Final MP3 verify karo (non-empty, valid duration), phir `present_file` se user ko do. Hinglish text file optional hai.
6. OCR warnings/empty pages user ko batao. Password-protected PDF ho to unlocked copy maango; password chat mein mat maango.

## Hinglish ka matlab
Default audio Hindi pronunciation mein hai. `--roman-text` approximate Roman-Hindi preview deta hai; yeh English translation nahi hai. Mixed Hindi-English source ke liye online Hindi neural voice zyada suitable ho sakti hai. User explicitly English translation maange to pehle reviewed translation banao, phir TTS karo.

## Limits aur honesty
- Web/CLI limits: 25 MB PDF, 500 pages, 10 lakh extracted characters. Badi book ko parts mein baanto; har part ka poora audio do.
- Local neural voice robotic eSpeak fallback nahi hai, lekin human-level naturalness guarantee nahi. Sample sunne ko do.
- Bundled voice ko conservative non-commercial/personal-use maano; commercial use se pehle upstream dataset license verify karo.
- Online Edge TTS unofficial free service hai; uptime/rate limits/provider terms guarantee nahi.
- Local mode mein text third-party ko nahi bheja jata. Online mode mein text chunks Microsoft ko jate hain; PDF nahi.
- Chat `generate_speech` tool ki per-turn clip limits ko full-book workaround mat banao; repo CLI/app full chunked conversion ke liye hai.
