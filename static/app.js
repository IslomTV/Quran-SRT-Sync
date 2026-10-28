/**
 * Quran SRT Sync - Frontend Application Logic
 * Audio synchronization, waveform generation, karaoke teleprompter, and CapCut export.
 */

// Application State
const state = {
  sessionId: null,
  audioFile: null,
  srtFile: null,
  audioDuration: 0,
  entries: [],
  syncedEntries: [],
  mode: 'preserve',
  currentPlayingIdx: -1
};

// DOM Elements
const audioDropzone = document.getElementById('audioDropzone');
const audioInput = document.getElementById('audioInput');
const audioFileName = document.getElementById('audioFileName');
const audioBadge = document.getElementById('audioBadge');

const srtDropzone = document.getElementById('srtDropzone');
const srtInput = document.getElementById('srtInput');
const srtFileName = document.getElementById('srtFileName');
const srtBadge = document.getElementById('srtBadge');

const btnUploadFiles = document.getElementById('btnUploadFiles');
const uploadStatusText = document.getElementById('uploadStatusText');
const btnLoadSample = document.getElementById('btnLoadSample');

const playerCard = document.getElementById('playerCard');
const audioElement = document.getElementById('audioElement');
const waveformContainer = document.getElementById('waveformContainer');
const currentTimeDisplay = document.getElementById('currentTimeDisplay');
const totalDurationDisplay = document.getElementById('totalDurationDisplay');
const surahBadgeContainer = document.getElementById('surahBadgeContainer');
const surahBadge = document.getElementById('surahBadge');

// Settings
const modeBtns = document.querySelectorAll('.mode-btn');
const wordsPerSubContainer = document.getElementById('wordsPerSubContainer');
const wordsPerSub = document.getElementById('wordsPerSub');
const whisperModel = document.getElementById('whisperModel');
const startPad = document.getElementById('startPad');
const startPadVal = document.getElementById('startPadVal');
const endPad = document.getElementById('endPad');
const endPadVal = document.getElementById('endPadVal');
const globalOffset = document.getElementById('globalOffset');
const globalOffsetVal = document.getElementById('globalOffsetVal');
const minDur = document.getElementById('minDur');
const minDurVal = document.getElementById('minDurVal');
const preventOverlaps = document.getElementById('preventOverlaps');
const repetitionMode = document.getElementById('repetitionMode');
const btnStartSync = document.getElementById('btnStartSync');

// Progress & Results
const progressCard = document.getElementById('progressCard');
const progressBar = document.getElementById('progressBar');
const progressPercent = document.getElementById('progressPercent');
const progressStatus = document.getElementById('progressStatus');

const resultsCard = document.getElementById('resultsCard');
const statDuration = document.getElementById('statDuration');
const statSubtitles = document.getElementById('statSubtitles');
const statPauses = document.getElementById('statPauses');
const statShift = document.getElementById('statShift');
const btnDownloadSRT = document.getElementById('btnDownloadSRT');
const btnCopySRT = document.getElementById('btnCopySRT');
const subtitlesList = document.getElementById('subtitlesList');
const alignmentWarning = document.getElementById('alignmentWarning');


// =========================================================================
// Drag and Drop Setup
// =========================================================================

function setupDropzone(dropzone, input, onFileSelect) {
  dropzone.addEventListener('click', () => input.click());

  ['dragenter', 'dragover'].forEach(name => {
    dropzone.addEventListener(name, (e) => {
      e.preventDefault();
      dropzone.classList.add('border-brand-500', 'bg-slate-800');
    });
  });

  ['dragleave', 'drop'].forEach(name => {
    dropzone.addEventListener(name, (e) => {
      e.preventDefault();
      dropzone.classList.remove('border-brand-500', 'bg-slate-800');
    });
  });

  dropzone.addEventListener('drop', (e) => {
    if (e.dataTransfer.files.length) {
      onFileSelect(e.dataTransfer.files[0]);
    }
  });

  input.addEventListener('change', () => {
    if (input.files.length) {
      onFileSelect(input.files[0]);
    }
  });
}

setupDropzone(audioDropzone, audioInput, (file) => {
  state.audioFile = file;
  audioFileName.textContent = file.name;
  audioBadge.textContent = `${(file.size / (1024 * 1024)).toFixed(1)} MB`;
  audioBadge.classList.remove('hidden');
  checkUploadReady();
});

setupDropzone(srtDropzone, srtInput, (file) => {
  state.srtFile = file;
  srtFileName.textContent = file.name;
  srtBadge.textContent = `${(file.size / 1024).toFixed(1)} KB`;
  srtBadge.classList.remove('hidden');
  checkUploadReady();
});

function checkUploadReady() {
  if (state.audioFile && state.srtFile) {
    btnUploadFiles.disabled = false;
    btnUploadFiles.classList.remove('bg-slate-800', 'text-slate-500', 'cursor-not-allowed');
    btnUploadFiles.classList.add('bg-brand-600', 'hover:bg-brand-500', 'text-white', 'shadow-lg');
    uploadStatusText.textContent = "Both files selected. Click Upload & Parse to proceed.";
  }
}


// =========================================================================
// Settings Listeners
// =========================================================================

modeBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    modeBtns.forEach(b => {
      b.classList.remove('active', 'border-brand-500', 'bg-brand-900/40', 'text-brand-300');
      b.classList.add('border-slate-700', 'bg-slate-800/40', 'text-slate-300');
    });
    btn.classList.add('active', 'border-brand-500', 'bg-brand-900/40', 'text-brand-300');
    btn.classList.remove('border-slate-700', 'bg-slate-800/40', 'text-slate-300');
    state.mode = btn.dataset.mode;

    if (state.mode === 'word') {
      wordsPerSubContainer.classList.remove('hidden');
    } else {
      wordsPerSubContainer.classList.add('hidden');
    }
  });
});

startPad.addEventListener('input', () => startPadVal.textContent = `${startPad.value} ms`);
endPad.addEventListener('input', () => endPadVal.textContent = `${endPad.value} ms`);
globalOffset.addEventListener('input', () => {
  const v = parseInt(globalOffset.value);
  globalOffsetVal.textContent = `${v > 0 ? '+' : ''}${v} ms`;
});
minDur.addEventListener('input', () => minDurVal.textContent = `${minDur.value} ms`);


// =========================================================================
// File Upload & Sample Loader
// =========================================================================

btnUploadFiles.addEventListener('click', async () => {
  if (!state.audioFile || !state.srtFile) return;

  const formData = new FormData();
  formData.append('audio_file', state.audioFile);
  formData.append('srt_file', state.srtFile);

  uploadStatusText.textContent = "Uploading & extracting acoustic features...";
  btnUploadFiles.disabled = true;

  try {
    const res = await fetch('/api/upload', {
      method: 'POST',
      body: formData
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Upload failed');
    }
    const data = await res.json();
    handleSessionLoaded(data);
  } catch (err) {
    alert(`Error: ${err.message}`);
    btnUploadFiles.disabled = false;
  }
});

btnLoadSample.addEventListener('click', async () => {
  btnLoadSample.textContent = "Loading Sample...";
  try {
    const res = await fetch('/api/load-sample');
    if (!res.ok) throw new Error('Failed to load sample');
    const data = await res.json();

    audioFileName.textContent = "al_fatiha.mp3 (Sample)";
    audioBadge.textContent = "Sample Audio";
    audioBadge.classList.remove('hidden');

    srtFileName.textContent = "al_fatiha_original.srt (Sample)";
    srtBadge.textContent = "Sample SRT";
    srtBadge.classList.remove('hidden');

    handleSessionLoaded(data);
  } catch (err) {
    alert(`Error: ${err.message}`);
  } finally {
    btnLoadSample.innerHTML = "<span>⚡</span> Load Sample (Al-Fatihah)";
  }
});

function handleSessionLoaded(data) {
  state.sessionId = data.session_id;
  state.audioDuration = data.audio_duration;
  state.entries = data.entries;

  // Show player card
  playerCard.classList.remove('hidden');
  audioElement.src = data.audio_url;

  if (data.surah_info) {
    surahBadge.textContent = `Surah ${data.surah_info.number}: ${data.surah_info.english_name} (${data.surah_info.arabic_name})`;
    surahBadgeContainer.classList.remove('hidden');
  } else {
    surahBadgeContainer.classList.add('hidden');
  }

  totalDurationDisplay.textContent = formatTime(data.audio_duration);

  // Render Waveform preview
  renderWaveform(data.waveform);

  // Enable Start Sync button
  btnStartSync.disabled = false;
  btnStartSync.classList.remove('bg-slate-800', 'text-slate-500', 'cursor-not-allowed');
  btnStartSync.classList.add('bg-gradient-to-r', 'from-brand-600', 'to-emerald-500', 'hover:from-brand-500', 'hover:to-emerald-400', 'text-white');
  uploadStatusText.textContent = `Loaded ${data.total_subtitles} subtitles. Ready to synchronize!`;
}

function renderWaveform(peaks) {
  waveformContainer.innerHTML = '';
  if (!peaks || !peaks.length) return;
  const max = Math.max(...peaks, 0.01);
  peaks.forEach((p, idx) => {
    const bar = document.createElement('div');
    const hPercent = Math.max(8, Math.round((p / max) * 100));
    bar.className = 'flex-1 bg-slate-700 hover:bg-brand-500 transition rounded-t-sm';
    bar.style.height = `${hPercent}%`;
    bar.dataset.index = idx;
    bar.title = `${((idx / peaks.length) * state.audioDuration).toFixed(1)}s`;
    bar.addEventListener('click', () => {
      const seekSec = (idx / peaks.length) * state.audioDuration;
      audioElement.currentTime = seekSec;
      audioElement.play();
    });
    waveformContainer.appendChild(bar);
  });
}


// =========================================================================
// Synchronization Trigger & Progress
// =========================================================================

btnStartSync.addEventListener('click', async () => {
  if (!state.sessionId) return;

  btnStartSync.disabled = true;
  progressCard.classList.remove('hidden');
  resultsCard.classList.add('hidden');

  let pct = 10;
  progressBar.style.width = `${pct}%`;
  progressPercent.textContent = `${pct}%`;
  progressStatus.textContent = "Analyzing acoustic spectrogram & voice activity...";

  const timer = setInterval(() => {
    if (pct < 85) {
      pct += 15;
      progressBar.style.width = `${pct}%`;
      progressPercent.textContent = `${pct}%`;
      if (pct === 40) progressStatus.textContent = "Phonetic ASR recognition & word timing extraction...";
      if (pct === 70) progressStatus.textContent = "Dynamic sequence alignment with Quranic text...";
      if (pct === 85) progressStatus.textContent = "Refining acoustic boundaries & applying CapCut padding...";
    }
  }, 1000);

  try {
    const res = await fetch('/api/synchronize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: state.sessionId,
        mode: state.mode,
        words_per_sub: parseInt(wordsPerSub.value) || 1,
        whisper_model: whisperModel.value,
        global_offset_ms: parseFloat(globalOffset.value),
        start_padding_ms: parseFloat(startPad.value),
        end_padding_ms: parseFloat(endPad.value),
        min_duration_ms: parseFloat(minDur.value),
        prevent_overlaps: preventOverlaps.checked,
        repetition_mode: repetitionMode ? repetitionMode.value : 'encompass'
      })
    });

    clearInterval(timer);

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Synchronization failed');
    }

    progressBar.style.width = `100%`;
    progressPercent.textContent = `100%`;
    progressStatus.textContent = "Synchronization complete!";

    const result = await res.json();
    setTimeout(() => {
      progressCard.classList.add('hidden');
      renderResults(result);
    }, 400);

  } catch (err) {
    clearInterval(timer);
    progressCard.classList.add('hidden');
    alert(`Sync Error: ${err.message}`);
  } finally {
    btnStartSync.disabled = false;
  }
});


// =========================================================================
// Results Rendering & Karaoke Teleprompter
// =========================================================================

function renderResults(result) {
  state.syncedEntries = result.synced_entries;
  resultsCard.classList.remove('hidden');

  if (result.stats.alignment_warning) {
    alignmentWarning.textContent = result.stats.alignment_warning;
    alignmentWarning.classList.remove('hidden');
  } else {
    alignmentWarning.textContent = '';
    alignmentWarning.classList.add('hidden');
  }

  // Stats
  statDuration.textContent = `${result.stats.audio_duration_sec}s`;
  statSubtitles.textContent = result.stats.total_subtitles;
  statPauses.textContent = result.stats.num_pauses_detected;
  statShift.textContent = `${result.stats.average_shift_sec > 0 ? '+' : ''}${result.stats.average_shift_sec}s`;

  // Download Link
  btnDownloadSRT.href = result.download_url;
  btnDownloadSRT.download = result.download_filename;

  // Render Subtitles
  subtitlesList.innerHTML = '';
  state.syncedEntries.forEach((entry, idx) => {
    const row = document.createElement('div');
    row.id = `sub-row-${idx}`;
    row.className = 'p-4 hover:bg-slate-800/40 transition cursor-pointer border-l-4 border-transparent flex flex-col sm:flex-row sm:items-center justify-between gap-3';
    if (entry.low_confidence) {
      row.classList.add('border-amber-500', 'bg-amber-950/20');
    }
    row.dataset.start = entry.start_sec;
    row.dataset.end = entry.end_sec;

    const shift = entry.shift_sec || 0;
    const shiftBadgeColor = Math.abs(shift) > 0.4 ? 'bg-amber-900/60 text-amber-400 border-amber-500/30' : 'bg-emerald-900/60 text-emerald-400 border-emerald-500/30';

    row.innerHTML = `
      <div class="flex items-center gap-3">
        <span class="text-xs font-mono font-bold text-slate-500 w-7">#${entry.index}</span>
        <div class="space-y-1.5">
          <div class="flex flex-wrap items-center gap-2">
            <div class="flex items-center gap-1.5 bg-brand-950/90 border border-brand-500/30 px-2.5 py-1 rounded-lg shadow-sm">
              <span class="text-[10px] font-semibold text-brand-400 uppercase tracking-wider">Updated:</span>
              <span class="text-xs font-mono font-bold text-brand-200">
                ${entry.start_str} &rarr; ${entry.end_str}
              </span>
            </div>
            <span class="text-[10px] font-mono px-2 py-0.5 rounded-full border ${shiftBadgeColor} font-medium">
              Δ ${shift > 0 ? '+' : ''}${shift.toFixed(3)}s
            </span>
            ${entry.low_confidence ? `
              <span class="text-[10px] font-semibold px-2 py-0.5 rounded-full border bg-amber-950/70 text-amber-300 border-amber-500/40">
                Review timing
              </span>
            ` : ''}
            ${entry.has_repetition ? `
              <span class="text-[10px] font-mono px-2 py-0.5 rounded-full border bg-purple-900/60 text-purple-300 border-purple-500/30 font-medium">
                🔁 Verse Repetition Encompassed
              </span>
            ` : ''}
          </div>
          ${entry.orig_start_str ? `
            <div class="flex items-center gap-2 text-[11px] font-mono text-slate-500">
              <span class="text-[10px] uppercase tracking-wider text-slate-600">Original SRT:</span>
              <span class="line-through text-slate-400/80">${entry.orig_start_str} &rarr; ${entry.orig_end_str}</span>
            </div>
          ` : ''}
        </div>
      </div>
      <div class="quran-text text-lg sm:text-xl text-slate-100 max-w-xl text-right">
        ${entry.text}
      </div>
    `;

    // Click row to seek audio
    row.addEventListener('click', () => {
      audioElement.currentTime = entry.start_sec;
      audioElement.play();
    });

    subtitlesList.appendChild(row);
  });
}


// =========================================================================
// Real-Time Audio Teleprompter & Karaoke Highlighting
// =========================================================================

audioElement.addEventListener('timeupdate', () => {
  const curTime = audioElement.currentTime;
  currentTimeDisplay.textContent = formatTime(curTime);

  if (!state.syncedEntries.length) return;

  // Find active subtitle
  let activeIdx = -1;
  for (let i = 0; i < state.syncedEntries.length; i++) {
    const e = state.syncedEntries[i];
    if (curTime >= e.start_sec && curTime <= e.end_sec) {
      activeIdx = i;
      break;
    }
  }

  if (activeIdx !== state.currentPlayingIdx) {
    // Remove old active
    if (state.currentPlayingIdx !== -1) {
      const oldRow = document.getElementById(`sub-row-${state.currentPlayingIdx}`);
      if (oldRow) {
        oldRow.classList.remove('active-karaoke');
      }
    }

    state.currentPlayingIdx = activeIdx;

    if (activeIdx !== -1) {
      const newRow = document.getElementById(`sub-row-${activeIdx}`);
      if (newRow) {
        newRow.classList.add('active-karaoke');
        // Auto scroll
        newRow.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }
  }
});


// =========================================================================
// Copy to Clipboard
// =========================================================================

btnCopySRT.addEventListener('click', () => {
  if (!state.syncedEntries.length) return;
  let text = '';
  state.syncedEntries.forEach((e, idx) => {
    text += `${idx + 1}\n${e.start_str} --> ${e.end_str}\n${e.text}\n\n`;
  });
  navigator.clipboard.writeText(text).then(() => {
    btnCopySRT.innerHTML = '<span>✅</span> Copied!';
    setTimeout(() => {
      btnCopySRT.innerHTML = '<span>📋</span> Copy SRT';
    }, 2000);
  });
});


// Helper time formatter
function formatTime(sec) {
  if (isNaN(sec)) return "00:00.0";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  const ds = Math.floor((sec % 1) * 10);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}.${ds}`;
}
