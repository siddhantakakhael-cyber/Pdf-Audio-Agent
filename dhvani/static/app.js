'use strict';
const $ = (id) => document.getElementById(id);
const ACTIVE = new Set(['extracting', 'queued', 'generating']);
const state = {
  session: null, health: null, job: null, dirty: false, romanRevision: -1,
  pollTimer: null, polling: false, pollErrors: 0, busy: false,
  resultBlob: null, resultJob: null, sampleBlob: null, toastTimer: null,
};
const storage = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch {} },
  remove(key) { try { localStorage.removeItem(key); } catch {} },
};
state.session = storage.get('dhvani-session');
if (!state.session || !/^[A-Za-z0-9-]{32,64}$/.test(state.session)) {
  state.session = crypto.randomUUID();
  storage.set('dhvani-session', state.session);
}

function toast(message, ms = 4500) {
  clearTimeout(state.toastTimer);
  $('toast').textContent = message;
  $('toast').hidden = false;
  state.toastTimer = setTimeout(() => { $('toast').hidden = true; }, ms);
}
async function api(path, { method = 'GET', body, raw = false } = {}) {
  const headers = { 'X-Dhvani-Session': state.session };
  if (method !== 'GET') headers['X-Dhvani-Client'] = 'web';
  let payload;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  let response;
  try { response = await fetch(path, { method, headers, body: payload, credentials: 'same-origin' }); }
  catch { throw new Error('Server se connection nahi hua. Network check karke refresh/retry karein.'); }
  if (!response.ok) {
    let message = `Request fail hui (${response.status}).`;
    try { const data = await response.json(); if (data.detail) message = typeof data.detail === 'string' ? data.detail : message; } catch {}
    throw new Error(message);
  }
  if (raw) return response.blob();
  if (response.status === 204) return null;
  return response.json();
}
function fmtBytes(bytes) {
  if (!bytes) return '0 KB';
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
function fmtDuration(seconds) {
  if (!seconds || !Number.isFinite(seconds)) return '';
  const s = Math.round(seconds), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h} hr ${m} min` : m ? `${m} min ${s % 60} sec` : `${s} sec`;
}
function selectedVoice() { return document.querySelector('input[name="voice"]:checked').value; }
function setBusy(value) {
  state.busy = value;
  $('choose-file').disabled = value;
  $('use-text').disabled = value || !$('paste-input').value.trim();
  $('sample-button').disabled = value;
  updateGenerateButton();
}
function updateGenerateButton() {
  const job = state.job;
  const ready = job && ['ready', 'failed', 'cancelled', 'completed'].includes(job.status) && job.char_count > 0;
  const localMissing = selectedVoice() === 'priyamvada' && state.health && !state.health.local_ready;
  $('generate-button').disabled = !ready || ACTIVE.has(job?.status) || state.busy || localMissing || state.dirty;
}
function setPercent(prefix, done, total) {
  const pct = total ? Math.min(100, Math.round(done / total * 100)) : 0;
  $(`${prefix}-bar`).style.width = `${pct}%`;
  $(`${prefix}-percent`).textContent = total ? `${pct}%` : '';
}
function statusText(job) {
  if (job.cancel_requested) return 'Rok rahe hain…';
  return ({ extracting: 'PDF padh rahe hain', queued: 'Queue mein', generating: 'Audio ban rahi hai', ready: 'Text ready', completed: 'MP3 ready', failed: 'Ruk gaya', cancelled: 'Cancelled' })[job.status] || job.status;
}
function renderJob() {
  const job = state.job;
  const has = Boolean(job);
  $('file-summary').hidden = !has;
  $('review-card').hidden = !has || !job.char_count;
  $('extract-progress').hidden = !has || job.status !== 'extracting';
  $('generation-progress').hidden = !has || !['queued', 'generating'].includes(job.status);
  $('error-box').hidden = !has || job.status !== 'failed';
  $('result-box').hidden = !has || job.status !== 'completed';
  $('source-tabs').hidden = has;
  if (has) {
    $('panel-upload').hidden = true;
    $('panel-paste').hidden = true;
    $('file-name').textContent = job.filename;
    const meta = [job.pages ? `${job.pages} pages` : '', job.pdf_bytes ? fmtBytes(job.pdf_bytes) : '', job.char_count ? `${job.char_count.toLocaleString('en-IN')} characters` : ''].filter(Boolean).join(' · ');
    $('file-meta').textContent = meta;
    $('file-status').textContent = statusText(job);
    $('char-count').textContent = `${job.char_count.toLocaleString('en-IN')} CHAR`;
    const warnings = job.warnings || [];
    $('warnings-box').hidden = !warnings.length;
    $('warning-count').textContent = `(${warnings.length})`;
    $('warnings-list').replaceChildren(...warnings.map((w) => { const li = document.createElement('li'); li.textContent = w; return li; }));
  }
  if (has && job.status === 'extracting') {
    $('extract-label').textContent = job.cancel_requested ? 'Cancel ho raha hai…' : 'PDF padhi ja rahi hai…';
    setPercent('extract', job.progress.done, job.progress.total);
    $('extract-cancel').disabled = Boolean(job.cancel_requested);
  }
  if (has && ['queued', 'generating'].includes(job.status)) {
    $('generation-label').textContent = job.cancel_requested ? 'Cancel ho raha hai…' : job.status === 'queued' ? 'Queue mein intezaar…' : 'Audio ban rahi hai…';
    setPercent('generation', job.progress.done, job.progress.total);
    $('chunk-label').textContent = job.progress.total ? `${job.progress.done} / ${job.progress.total} audio chunks complete` : 'Chunks taiyaar ho rahe hain…';
    $('generation-cancel').disabled = Boolean(job.cancel_requested);
  }
  if (has && job.status === 'failed') {
    $('error-message').textContent = job.error || 'Dobara try karein.';
    $('switch-local').hidden = job.error_code !== 'edge_unavailable' || !state.health?.local_ready;
    $('retry-button').disabled = state.busy;
  }
  if (has && job.status === 'completed' && job.audio) {
    $('result-meta').textContent = [fmtDuration(job.audio.duration), fmtBytes(job.audio.bytes), 'MP3'].filter(Boolean).join(' · ');
    loadResultAudio().catch((e) => toast(e.message));
  }
  if (!has || !ACTIVE.has(job.status)) {
    const words = job?.char_count ? Math.round(job.char_count / 6) : 0;
    $('estimate').textContent = has && job.char_count ? `Lagbhag ${Math.max(1, Math.round(words / 140))} min audio · exact length generate ke baad` : 'Pehle PDF upload ya text paste karein.';
  } else $('estimate').textContent = 'Poora text chunks mein convert ho raha hai. Tab khula rakhein.';
  $('save-text').disabled = !state.dirty || state.busy || ACTIVE.has(job?.status);
  updateGenerateButton();
}
async function loadText() {
  if (!state.job) return;
  const data = await api(`/api/jobs/${state.job.id}/text`);
  if (!state.dirty) $('review-text').value = data.text;
  state.romanRevision = -1;
  $('roman-text').value = '';
}
async function loadRoman() {
  if (!state.job) return;
  if (state.dirty) await saveText();
  if (state.romanRevision === state.job.revision) return;
  $('roman-text').value = 'Roman Hindi ban rahi hai…';
  const data = await api(`/api/jobs/${state.job.id}/text?roman=true`);
  $('roman-text').value = data.text;
  state.romanRevision = state.job.revision;
}
async function saveText() {
  if (!state.job || !state.dirty) return;
  setBusy(true);
  try {
    const text = $('review-text').value;
    state.job = await api(`/api/jobs/${state.job.id}/text`, { method: 'PUT', body: { text } });
    state.dirty = false;
    state.romanRevision = -1;
    clearResult();
    $('save-status').textContent = 'Saved ✓';
    renderJob();
    if (!$('roman-view').hidden) await loadRoman();
  } finally { setBusy(false); }
}
function clearResult() {
  if (state.resultBlob) URL.revokeObjectURL(state.resultBlob);
  state.resultBlob = null; state.resultJob = null;
  $('result-audio').removeAttribute('src');
}
async function loadResultAudio() {
  const job = state.job;
  if (!job || job.status !== 'completed' || state.resultJob === job.id) return;
  const blob = await api(job.download_url, { raw: true });
  if (state.job?.id !== job.id) return;
  clearResult();
  state.resultBlob = URL.createObjectURL(blob); state.resultJob = job.id;
  $('result-audio').src = state.resultBlob;
}
function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}
async function downloadResult() {
  if (!state.job?.audio) return;
  $('download-button').disabled = true;
  try {
    await loadResultAudio();
    const response = await fetch($('result-audio').src);
    saveBlob(await response.blob(), state.job.audio.filename);
    toast('MP3 download start ho gaya. Browser ke downloads mein check karein.');
  } finally { $('download-button').disabled = false; }
}
function stopPolling() { clearTimeout(state.pollTimer); state.pollTimer = null; }
async function poll() {
  if (!state.job || state.polling) return;
  state.polling = true;
  try {
    const job = await api(`/api/jobs/${state.job.id}`);
    state.pollErrors = 0;
    const wasReady = state.job.char_count > 0;
    state.job = job;
    storage.set('dhvani-current', job.id);
    renderJob();
    if (job.char_count && !wasReady && !state.dirty) await loadText();
    if (ACTIVE.has(job.status)) state.pollTimer = setTimeout(poll, 1200);
    else if (job.status === 'ready') toast('Text ready hai. Review karke MP3 banaiye.');
    else if (job.status === 'completed') toast('Poora MP3 taiyaar hai!');
  } catch (e) {
    state.pollErrors += 1;
    if (state.pollErrors <= 3) toast(e.message);
    state.pollTimer = setTimeout(poll, Math.min(10000, 1500 * state.pollErrors));
  } finally { state.polling = false; }
}
async function adoptJob(job) {
  stopPolling(); clearResult(); state.dirty = false; state.job = job;
  storage.set('dhvani-current', job.id);
  $('save-status').textContent = '';
  renderJob();
  if (job.char_count) await loadText();
  if (ACTIVE.has(job.status)) poll();
}
async function uploadFile(file) {
  if (!file) return;
  const max = (state.health?.limits.pdf_mb || 25) * 1024 * 1024;
  if (!file.name.toLowerCase().endsWith('.pdf')) { toast('Sirf .pdf file choose karein.'); return; }
  if (file.size > max) { toast(`PDF ${state.health?.limits.pdf_mb || 25} MB se chhoti honi chahiye.`); return; }
  setBusy(true);
  const form = new FormData(); form.append('file', file); form.append('ocr', $('ocr-toggle').checked ? 'true' : 'false');
  try { const job = await api('/api/jobs', { method: 'POST', body: form }); await adoptJob(job); }
  finally { setBusy(false); $('file-input').value = ''; }
}
async function usePastedText() {
  const text = $('paste-input').value.trim();
  if (!text) return;
  setBusy(true);
  try { await adoptJob(await api('/api/text-jobs', { method: 'POST', body: { text } })); }
  finally { setBusy(false); }
}
async function generate() {
  if (!state.job) return;
  setBusy(true);
  try {
    if (state.dirty) await saveText();
    state.job = await api(`/api/jobs/${state.job.id}/generate`, { method: 'POST', body: { voice: selectedVoice(), speed: Number($('speed').value) } });
    clearResult(); renderJob(); poll();
  } finally { setBusy(false); }
}
async function retry(local = false) {
  if (!state.job) return;
  if (local) { document.querySelector('input[value="priyamvada"]').checked = true; updateVoiceUI(); }
  setBusy(true);
  try {
    const body = local ? { voice: 'priyamvada', speed: Number($('speed').value) } : {};
    state.job = await api(`/api/jobs/${state.job.id}/retry`, { method: 'POST', body });
    renderJob(); poll();
  } finally { setBusy(false); }
}
async function cancelJob(kind) {
  if (!state.job) return;
  const button = $(kind === 'extract' ? 'extract-cancel' : 'generation-cancel');
  button.disabled = true;
  try { state.job = await api(`/api/jobs/${state.job.id}/cancel`, { method: 'POST', body: {} }); renderJob(); poll(); }
  catch (e) { button.disabled = false; throw e; }
}
function invalidateSample() {
  if (state.sampleBlob) URL.revokeObjectURL(state.sampleBlob);
  state.sampleBlob = null;
  $('sample-audio').pause(); $('sample-audio').removeAttribute('src'); $('sample-audio').hidden = true;
}
async function playSample() {
  setBusy(true);
  const button = $('sample-button'); const old = button.textContent; button.textContent = 'Sample ban raha hai…';
  try {
    const blob = await api('/api/sample', { method: 'POST', raw: true, body: { voice: selectedVoice(), speed: Number($('speed').value) } });
    invalidateSample(); state.sampleBlob = URL.createObjectURL(blob);
    $('sample-audio').src = state.sampleBlob; $('sample-audio').hidden = false;
    await $('sample-audio').play();
  } finally { button.textContent = old; setBusy(false); }
}
function updateVoiceUI() {
  document.querySelectorAll('.voice-option').forEach((label) => label.classList.toggle('selected', label.querySelector('input').checked));
  const local = selectedVoice() === 'priyamvada';
  $('voice-privacy').textContent = local ? '◈ Local mode: text kisi aur service ko nahi jata.' : '◈ Online mode: text chunks Microsoft Edge TTS ko jate hain; PDF nahi. Internet chahiye.';
  invalidateSample(); updateGenerateButton();
}
function switchSource(mode) {
  const upload = mode === 'upload';
  $('tab-upload').classList.toggle('active', upload); $('tab-upload').setAttribute('aria-selected', String(upload));
  $('tab-paste').classList.toggle('active', !upload); $('tab-paste').setAttribute('aria-selected', String(!upload));
  $('panel-upload').hidden = !upload; $('panel-paste').hidden = upload;
}
function switchTextView(roman) {
  $('tab-original').classList.toggle('active', !roman); $('tab-original').setAttribute('aria-selected', String(!roman));
  $('tab-roman').classList.toggle('active', roman); $('tab-roman').setAttribute('aria-selected', String(roman));
  $('original-view').hidden = roman; $('roman-view').hidden = !roman;
  if (roman) loadRoman().catch((e) => { $('roman-text').value = ''; toast(e.message); });
}
async function newJob() {
  const old = state.job;
  stopPolling(); clearResult(); invalidateSample(); state.job = null; state.dirty = false;
  storage.remove('dhvani-current');
  $('review-text').value = ''; $('roman-text').value = ''; $('paste-input').value = ''; $('paste-count').textContent = '0 characters';
  $('file-summary').hidden = true; $('review-card').hidden = true; $('result-box').hidden = true; $('error-box').hidden = true;
  $('generation-progress').hidden = true; $('extract-progress').hidden = true; $('source-tabs').hidden = false;
  switchSource('upload'); renderJob();
  if (old && !ACTIVE.has(old.status)) api(`/api/jobs/${old.id}`, { method: 'DELETE' }).catch(() => {});
}
function wireEvents() {
  $('help-button').addEventListener('click', () => $('help-dialog').showModal());
  $('close-help').addEventListener('click', () => $('help-dialog').close());
  $('help-dialog').addEventListener('click', (e) => { if (e.target === $('help-dialog')) { const r = e.target.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) e.target.close(); } });
  $('tab-upload').addEventListener('click', () => switchSource('upload'));
  $('tab-paste').addEventListener('click', () => switchSource('paste'));
  $('tab-original').addEventListener('click', () => switchTextView(false));
  $('tab-roman').addEventListener('click', () => switchTextView(true));
  $('choose-file').addEventListener('click', () => $('file-input').click());
  $('file-input').addEventListener('change', (e) => uploadFile(e.target.files[0]).catch((err) => toast(err.message)));
  const zone = $('dropzone');
  ['dragenter', 'dragover'].forEach((name) => zone.addEventListener(name, (e) => { e.preventDefault(); zone.classList.add('dragover'); }));
  ['dragleave', 'drop'].forEach((name) => zone.addEventListener(name, (e) => { e.preventDefault(); zone.classList.remove('dragover'); }));
  zone.addEventListener('drop', (e) => { if (!state.busy) uploadFile(e.dataTransfer.files[0]).catch((err) => toast(err.message)); });
  $('paste-input').addEventListener('input', () => { const n = $('paste-input').value.length; $('paste-count').textContent = `${n.toLocaleString('en-IN')} characters`; $('use-text').disabled = state.busy || !n; });
  $('use-text').addEventListener('click', () => usePastedText().catch((e) => toast(e.message)));
  $('review-text').addEventListener('input', () => { state.dirty = true; state.romanRevision = -1; $('save-status').textContent = 'Unsaved changes'; renderJob(); });
  $('save-text').addEventListener('click', () => saveText().catch((e) => toast(e.message)));
  $('download-text').addEventListener('click', async () => { try { if (state.dirty) await saveText(); const roman = !$('roman-view').hidden; const blob = await api(`/api/jobs/${state.job.id}/text?download=true&roman=${roman}`, { raw: true }); saveBlob(blob, roman ? 'dhvani-hinglish.txt' : 'dhvani-text.txt'); } catch (e) { toast(e.message); } });
  document.querySelectorAll('input[name="voice"]').forEach((input) => input.addEventListener('change', updateVoiceUI));
  $('speed').addEventListener('input', () => { $('speed-value').textContent = `${Number($('speed').value).toFixed(2).replace(/0$/, '')}×`; invalidateSample(); });
  $('sample-button').addEventListener('click', () => playSample().catch((e) => toast(e.message, 7000)));
  $('generate-button').addEventListener('click', () => generate().catch((e) => toast(e.message)));
  $('retry-button').addEventListener('click', () => retry(false).catch((e) => toast(e.message)));
  $('switch-local').addEventListener('click', () => retry(true).catch((e) => toast(e.message)));
  $('extract-cancel').addEventListener('click', () => cancelJob('extract').catch((e) => toast(e.message)));
  $('generation-cancel').addEventListener('click', () => cancelJob('generation').catch((e) => toast(e.message)));
  $('download-button').addEventListener('click', () => downloadResult().catch((e) => toast(e.message)));
  $('new-job').addEventListener('click', () => newJob().catch((e) => toast(e.message)));
  window.addEventListener('beforeunload', (e) => { if (ACTIVE.has(state.job?.status) || state.dirty) { e.preventDefault(); e.returnValue = ''; } });
}
async function init() {
  wireEvents(); updateVoiceUI();
  try {
    state.health = await api('/api/health');
    $('service-status').textContent = ''; const dot = document.createElement('span'); dot.className = 'dot';
    $('service-status').append(dot, document.createTextNode(state.health.local_ready ? 'Local voice ready' : 'Setup needed'));
    $('service-status').classList.toggle('offline', !state.health.local_ready);
    $('setup-banner').hidden = state.health.local_ready;
    $('ocr-toggle').disabled = !state.health.ocr_ready;
    if (!state.health.ocr_ready) $('ocr-toggle').checked = false;
    $('upload-limits').textContent = `${state.health.limits.pdf_mb} MB tak · ${state.health.limits.pages} pages · PDF format`;
    $('help-limits').textContent = `PDF: ${state.health.limits.pdf_mb} MB / ${state.health.limits.pages} pages. Text: ${state.health.limits.characters.toLocaleString('en-IN')} characters. Isse badi kitab ko parts mein baantein. Audio length par alag 10-minute cap nahi hai.`;
  } catch (e) { $('service-status').textContent = 'Server offline'; $('service-status').classList.add('offline'); toast(e.message); }
  const current = storage.get('dhvani-current');
  if (current) {
    try { await adoptJob(await api(`/api/jobs/${current}`)); }
    catch { storage.remove('dhvani-current'); }
  }
  setBusy(false);
}
init().catch((e) => toast(e.message));
