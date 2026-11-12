# Third-party notices

Dhvani's application code is GPL-3.0-or-later (see `LICENSE`). Downloaded assets
are separate works and keep their own licenses; they are stored in `.runtime/`
and are not committed to Git.

## Local Hindi voice
- Voice: Piper `hi_IN-priyamvada-medium` (female, 22,050 Hz).
- Original voice catalog: `rhasspy/piper-voices` (Hindi / hi_IN / priyamvada / medium).
- Download mirror used by the setup script: `anmol-shrivastav/tts-hindi`, pinned
  commit `1aa621cac173d940536e6d8376779094a122abaf`.
- Original ONNX SHA-256 before metadata conversion:
  `aa63bcf2cd493b55a450f280e23cf77f03afc9af7015e6e5acd43b652f166c88`.
- The setup script adds sherpa-onnx metadata and generates `tokens.txt` from the
  upstream phoneme map. The prepared model hash is recorded in
  `.runtime/assets_manifest.json`.
- License caution: public sources disagree (some voice indexes say MIT, while
  recent audits and downstream projects report the underlying IndicTTS dataset
  as CC BY-NC-SA 4.0 / non-commercial). Until the upstream dataset license is
  verified, this project treats the bundled voice as **personal/non-commercial
  use only**. Do not assume commercial rights from the mirror repository's MIT
  code license. Verify the original dataset/model terms before commercial use.

## sherpa-onnx
- Runtime: https://github.com/k2-fsa/sherpa-onnx — Apache-2.0.
- Piper conversion metadata procedure follows the sherpa-onnx Piper docs.

## eSpeak NG data
- Bundled `espeak-ng-data` is obtained from the `piper/espeak-ng-data` directory
  of `iprincegarg/hawkeye-api`, pinned commit
  `c819e517f1dbacb3b479997a4dd832e681f11139`.
- Original project: https://github.com/espeak-ng/espeak-ng — GPL-3.0-or-later.
  Critical data files are verified against the pinned Git blob hashes.

## OCR
- Runtime: `tesserocr` / Tesseract OCR — Apache-2.0.
- Language data: `tesseract-ocr/tessdata_fast` (`hin`, `eng`), pinned commit
  `87416418657359cb625c412a48b6e1d6d41c29bd` — Apache-2.0 repository license.
  Check individual model provenance if redistributing commercially.

## Online voices (optional)
- `edge-tts` Python package: https://github.com/rany2/edge-tts — GPL-3.0.
- Voices `hi-IN-SwaraNeural` and `hi-IN-MadhurNeural` are served by Microsoft's
  Edge Read Aloud online service. No API key is required by the package, but the
  service is unofficial, network-dependent, and subject to provider availability,
  rate limits, and terms. It is not an offline or guaranteed-free commercial API.

## Other dependencies
FastAPI, Uvicorn, PyMuPDF, Pillow, indic-transliteration, mutagen, NumPy, ONNX,
and imageio-ffmpeg retain their respective licenses. PyMuPDF is AGPL/commercial
dual-licensed; review it before distributing a closed-source product. FFmpeg
binary licensing depends on its build; the bundled imageio-ffmpeg wheel includes
an FFmpeg build with libmp3lame. Review FFmpeg/LAME terms for redistribution.
