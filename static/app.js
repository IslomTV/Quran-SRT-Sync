/**
 * Quran SRT Sync - Frontend Application Logic
 * Audio synchronization, waveform generation, karaoke teleprompter, and SRT export.
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
const bulkAudioDir = document.getElementById('bulkAudioDir');
const bulkSrtDir = document.getElementById('bulkSrtDir');
const btnBulkScan = document.getElementById('btnBulkScan');
const btnBulkStart = document.getElementById('btnBulkStart');
const bulkStatus = document.getElementById('bulkStatus');
const bulkProgress = document.getElementById('bulkProgress');
const bulkProgressText = document.getElementById('bulkProgressText');
const bulkProgressCount = document.getElementById('bulkProgressCount');
const bulkProgressBar = document.getElementById('bulkProgressBar');
const bulkMatchesPanel = document.getElementById('bulkMatchesPanel');
const bulkMatchesList = document.getElementById('bulkMatchesList');
const bulkIssues = document.getElementById('bulkIssues');
let bulkPairs = [];
let bulkRows = [];

const sectionTabs = [...document.querySelectorAll('[role="tab"][aria-controls]')];
const generatorTab = document.getElementById('generatorTab');
const sectionPanels = sectionTabs.map((tab) =>
  document.getElementById(tab.getAttribute('aria-controls'))
);
const singleSyncWorkflow = document.getElementById('singleSyncWorkflow');

function activateSectionTab(index, moveFocus = false) {
  sectionTabs.forEach((tab, tabIndex) => {
    const active = tabIndex === index;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    tab.classList.toggle('bg-slate-800', active);
    tab.classList.toggle('text-white', active);
    tab.classList.toggle('shadow-sm', active);
    tab.classList.toggle('text-slate-400', !active);
    sectionPanels[tabIndex].hidden = !active;
  });
  singleSyncWorkflow.hidden = sectionTabs[index].id !== 'bulkTab';
  if (moveFocus) sectionTabs[index].focus();
}

sectionTabs.forEach((tab, index) => {
  tab.addEventListener('click', () => activateSectionTab(index));
  tab.addEventListener('keydown', (event) => {
    let nextIndex;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
      nextIndex = (index + 1) % sectionTabs.length;
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      nextIndex = (index - 1 + sectionTabs.length) % sectionTabs.length;
    } else if (event.key === 'Home') {
      nextIndex = 0;
    } else if (event.key === 'End') {
      nextIndex = sectionTabs.length - 1;
    }
    if (nextIndex !== undefined) {
      event.preventDefault();
      activateSectionTab(nextIndex, true);
    }
  });
});

activateSectionTab(Math.max(0, sectionTabs.findIndex(
  (tab) => tab.getAttribute('aria-selected') === 'true'
)));


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
// Bulk Synchronization
// =========================================================================

function setBulkButtonEnabled(button, enabled) {
  button.disabled = !enabled;
  button.classList.toggle('bg-brand-600', enabled);
  button.classList.toggle('hover:bg-brand-500', enabled);
  button.classList.toggle('text-white', enabled);
  button.classList.toggle('shadow-lg', enabled);
  button.classList.toggle('bg-slate-800', !enabled);
  button.classList.toggle('text-slate-500', !enabled);
  button.classList.toggle('cursor-not-allowed', !enabled);
}

function renderBulkIssues(issues) {
  bulkIssues.replaceChildren();
  issues.forEach((issue) => {
    const item = document.createElement('li');
    item.textContent = issue;
    bulkIssues.appendChild(item);
  });
  bulkIssues.classList.toggle('hidden', issues.length === 0);
}

btnBulkScan.addEventListener('click', async () => {
  const audioDir = bulkAudioDir.value.trim();
  const srtDir = bulkSrtDir.value.trim();
  if (!audioDir || !srtDir) {
    bulkStatus.textContent = 'Enter both folder paths before scanning.';
    return;
  }

  btnBulkScan.disabled = true;
  bulkAudioDir.disabled = true;
  bulkSrtDir.disabled = true;
  setBulkButtonEnabled(btnBulkStart, false);
  bulkStatus.textContent = 'Scanning MP3 files and matching Arabic SRTs...';
  bulkProgress.classList.add('hidden');
  bulkMatchesPanel.classList.add('hidden');
  renderBulkIssues([]);
  bulkMatchesList.replaceChildren();
  bulkPairs = [];
  bulkRows = [];

  try {
    const response = await fetch('/api/bulk/pairs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ audio_dir: audioDir, srt_dir: srtDir })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Could not scan folders.');

    bulkPairs = data.matches;
    const visibleIssues = (data.issues || []).filter(
      (issue) => !/^No matching MP3 files? found for /i.test(issue)
    );
    renderBulkIssues(visibleIssues);
    bulkPairs.forEach((pair) => {
      const row = document.createElement('tr');
      const audioCell = document.createElement('td');
      const srtCell = document.createElement('td');
      const resultCell = document.createElement('td');
      audioCell.className = 'px-3 py-2 text-slate-200 font-mono';
      srtCell.className = 'px-3 py-2 text-slate-300 font-mono';
      resultCell.className = 'px-3 py-2 text-slate-400';
      audioCell.textContent = pair.audio_filename;
      srtCell.textContent = pair.srt_filename;
      resultCell.textContent = 'Waiting';
      row.append(audioCell, srtCell, resultCell);
      bulkMatchesList.appendChild(row);
      bulkRows.push(resultCell);
    });

    bulkMatchesPanel.classList.toggle('hidden', bulkPairs.length === 0);
    bulkStatus.textContent = bulkPairs.length
      ? `${bulkPairs.length} pair(s) ready. Output folder: ${data.output_dir}`
      : 'No matching audio/SRT pairs found.';
    setBulkButtonEnabled(btnBulkStart, bulkPairs.length > 0);
  } catch (error) {
    bulkStatus.textContent = `Folder scan failed: ${error.message}`;
  } finally {
    btnBulkScan.disabled = false;
    bulkAudioDir.disabled = false;
    bulkSrtDir.disabled = false;
  }
});

btnBulkStart.addEventListener('click', async () => {
  if (!bulkPairs.length) return;

  const audioDir = bulkAudioDir.value.trim();
  const srtDir = bulkSrtDir.value.trim();
  setBulkButtonEnabled(btnBulkStart, false);
  btnBulkScan.disabled = true;
  bulkAudioDir.disabled = true;
  bulkSrtDir.disabled = true;
  bulkProgress.classList.remove('hidden');
  bulkProgressBar.style.width = '0%';
  bulkProgressCount.textContent = `0 / ${bulkPairs.length}`;
  let succeeded = 0;
  let failed = 0;

  for (let index = 0; index < bulkPairs.length; index += 1) {
    const pair = bulkPairs[index];
    bulkProgressText.textContent = `Processing ${pair.audio_filename} with ${pair.srt_filename}`;
    bulkRows[index].textContent = 'Synchronizing...';
    try {
      const response = await fetch('/api/bulk/synchronize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          audio_dir: audioDir,
          srt_dir: srtDir,
          audio_filename: pair.audio_filename,
          srt_filename: pair.srt_filename,
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
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Synchronization failed.');

      succeeded += 1;
      bulkRows[index].textContent = data.stats.alignment_warning
        ? `Saved: ${data.output_path} — ${data.stats.alignment_warning}`
        : `Saved: ${data.output_path}`;
      bulkRows[index].classList.remove('text-slate-400');
      bulkRows[index].classList.add(data.stats.alignment_warning ? 'text-amber-300' : 'text-emerald-400');
    } catch (error) {
      failed += 1;
      bulkRows[index].textContent = `Failed: ${error.message}`;
      bulkRows[index].classList.remove('text-slate-400');
      bulkRows[index].classList.add('text-red-400');
    }

    const completed = index + 1;
    const percent = Math.round((completed / bulkPairs.length) * 100);
    bulkProgressBar.style.width = `${percent}%`;
    bulkProgressCount.textContent = `${completed} / ${bulkPairs.length}`;
  }

  bulkProgressText.textContent = `Finished: ${succeeded} succeeded, ${failed} failed.`;
  bulkStatus.textContent = `Bulk synchronization complete. Check each result and review any low-confidence warnings.`;
  btnBulkScan.disabled = false;
  bulkAudioDir.disabled = false;
  bulkSrtDir.disabled = false;
});

[bulkAudioDir, bulkSrtDir].forEach((input) => {
  input.addEventListener('input', () => {
    bulkPairs = [];
    bulkRows = [];
    bulkMatchesList.replaceChildren();
    bulkMatchesPanel.classList.add('hidden');
    renderBulkIssues([]);
    bulkProgress.classList.add('hidden');
    setBulkButtonEnabled(btnBulkStart, false);
    bulkStatus.textContent = 'Folder paths changed. Find matching files again.';
  });
});

// =========================================================================
// CapCut Subtitle Timing
// =========================================================================

const capcutProjectsDir = document.getElementById('capcutProjectsDir');
const capcutSrtDir = document.getElementById('capcutSrtDir');
const btnCapcutPreview = document.getElementById('btnCapcutPreview');
const btnCapcutApply = document.getElementById('btnCapcutApply');
const capcutStatus = document.getElementById('capcutStatus');
const capcutSummary = document.getElementById('capcutSummary');
const capcutIssues = document.getElementById('capcutIssues');
const capcutProjectsPanel = document.getElementById('capcutProjectsPanel');
const capcutProjectsList = document.getElementById('capcutProjectsList');
const capcutInputs = [capcutProjectsDir, capcutSrtDir];
let capcutPreview = null;
let capcutBusy = false;

function setCapcutApplyEnabled(enabled) {
  btnCapcutApply.disabled = !enabled;
  btnCapcutApply.classList.toggle('bg-brand-600', enabled);
  btnCapcutApply.classList.toggle('hover:bg-brand-500', enabled);
  btnCapcutApply.classList.toggle('text-white', enabled);
  btnCapcutApply.classList.toggle('shadow-lg', enabled);
  btnCapcutApply.classList.toggle('bg-slate-800', !enabled);
  btnCapcutApply.classList.toggle('text-slate-500', !enabled);
  btnCapcutApply.classList.toggle('cursor-not-allowed', !enabled);
}

function formatCapcutTime(microseconds) {
  const milliseconds = Math.floor(microseconds / 1000);
  const hours = Math.floor(milliseconds / 3600000);
  const minutes = Math.floor((milliseconds % 3600000) / 60000);
  const seconds = Math.floor((milliseconds % 60000) / 1000);
  const millis = milliseconds % 1000;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(millis).padStart(3, '0')}`;
}

function clearCapcutPreview(message = 'Settings changed. Preview again before applying.') {
  capcutPreview = null;
  setCapcutApplyEnabled(false);
  capcutSummary.classList.add('hidden');
  capcutIssues.classList.add('hidden');
  capcutProjectsPanel.classList.add('hidden');
  capcutProjectsList.replaceChildren();
  if (!capcutBusy) capcutStatus.textContent = message;
}

function renderCapcutPreview(data) {
  capcutPreview = data;
  const summaryItems = [
    ['Project pairs', data.summary.pairs],
    ['Eligible', data.summary.eligible],
    ['Blocked', data.summary.blocked],
    ['Folder issues', data.summary.issues]
  ];
  capcutSummary.replaceChildren();
  summaryItems.forEach(([label, value]) => {
    const card = document.createElement('div');
    card.className = 'rounded-lg border border-slate-800 bg-slate-800/50 px-3 py-2';
    const number = document.createElement('div');
    number.className = 'text-lg font-semibold text-white';
    number.textContent = String(value);
    const caption = document.createElement('div');
    caption.className = 'text-[10px] uppercase tracking-wider text-slate-400';
    caption.textContent = label;
    card.append(number, caption);
    capcutSummary.appendChild(card);
  });
  capcutSummary.classList.remove('hidden');

  const issues = [...(data.issues || [])];
  capcutIssues.replaceChildren();
  issues.forEach((issue) => {
    const item = document.createElement('p');
    item.className = 'mb-1 last:mb-0';
    item.textContent = issue;
    capcutIssues.appendChild(item);
  });
  capcutIssues.classList.toggle('hidden', issues.length === 0);

  capcutProjectsList.replaceChildren();
  data.projects.forEach((project) => {
    const row = document.createElement('tr');
    row.className = project.eligible ? 'bg-emerald-500/[0.03]' : 'bg-amber-500/[0.025]';

    const selectCell = document.createElement('td');
    selectCell.className = 'px-3 py-3 align-top';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'capcut-project-select accent-brand-500';
    checkbox.value = project.number;
    checkbox.checked = project.eligible;
    checkbox.disabled = !project.eligible;
    checkbox.setAttribute('aria-label', `Select project ${project.project_name}`);
    checkbox.addEventListener('change', updateCapcutApplyButton);
    selectCell.appendChild(checkbox);

    const projectCell = document.createElement('td');
    projectCell.className = 'px-3 py-3 align-top';
    const projectName = document.createElement('div');
    projectName.className = 'font-medium text-slate-100';
    projectName.textContent = project.project_name;
    const srtName = document.createElement('div');
    srtName.className = 'mt-1 font-mono text-slate-400';
    srtName.textContent = project.srt_filename;
    projectCell.append(projectName, srtName);

    const textCell = document.createElement('td');
    textCell.className = 'px-3 py-3 align-top text-slate-300';
    const counts = project.subtitle_counts;
    textCell.textContent = `${counts.matched} matched / ${counts.srt} SRT / ${counts.capcut} CapCut` +
      (counts.split_groups ? ` · ${counts.split_groups} split group(s)` : '');

    const detailCell = document.createElement('td');
    detailCell.className = 'px-3 py-3 align-top';
    const status = document.createElement('span');
    status.className = project.eligible ? 'font-semibold text-emerald-400' : 'font-semibold text-amber-300';
    status.textContent = project.eligible ? 'Ready' : 'Blocked';
    detailCell.appendChild(status);

    const detailList = document.createElement('ul');
    detailList.className = 'mt-2 space-y-1 text-slate-400';
    project.matches.forEach((match) => {
      const item = document.createElement('li');
      item.className = 'text-slate-300';
      const capcutRange = match.split_count > 1
        ? `CapCut #${match.capcut_indices[0]}–#${match.capcut_indices[match.capcut_indices.length - 1]} (${match.split_count} split clips)`
        : `CapCut #${match.capcut_index}`;
      item.textContent = `SRT #${match.srt_index} → ${capcutRange} · ${formatCapcutTime(match.start)}–${formatCapcutTime(match.end)} · ${match.text}`;
      detailList.appendChild(item);
    });
    const resolutionSelects = [];
    const resolvePanel = document.createElement('div');
    resolvePanel.className = 'mt-2 space-y-2 rounded-lg border border-amber-500/30 bg-amber-500/[0.06] p-3';
    const resolveHeading = document.createElement('div');
    resolveHeading.className = 'text-sm font-semibold text-amber-200';
    resolveHeading.textContent = 'Choose the CapCut clips for each ambiguous SRT subtitle';
    resolvePanel.appendChild(resolveHeading);
    (project.unmatched_srt || []).forEach((subtitle) => {
      const item = document.createElement('li');
      const ambiguous = (project.ambiguous_matches || []).find(
        (match) => match.srt_index === subtitle.index
      );
      if (!ambiguous) {
        item.className = 'text-rose-300';
        item.textContent = `Unmatched SRT #${subtitle.index}: ${subtitle.text}`;
        detailList.appendChild(item);
        return;
      }

      item.className = 'flex flex-wrap items-center gap-2 text-amber-100';
      const label = document.createElement('label');
      label.className = 'text-sm';
      label.textContent = `SRT #${subtitle.index}:`;
      const select = document.createElement('select');
      select.className = 'rounded border border-slate-600 bg-slate-900 px-2 py-1 text-slate-100';
      select.setAttribute('aria-label', `Choose CapCut clips for SRT ${subtitle.index}`);
      ambiguous.candidates.forEach((group) => {
        const option = document.createElement('option');
        option.value = JSON.stringify(group);
        const range = group.length > 1
          ? `CapCut #${group[0]}–#${group[group.length - 1]} (${group.length} clips)`
          : `CapCut #${group[0]}`;
        option.textContent = range;
        select.appendChild(option);
      });
      resolutionSelects.push({ srtIndex: subtitle.index, select });
      label.appendChild(select);
      resolvePanel.appendChild(label);
    });
    if (resolutionSelects.length) {
      const resolveItem = document.createElement('div');
      resolveItem.className = 'mt-2';
      const resolveButton = document.createElement('button');
      resolveButton.type = 'button';
      resolveButton.className = 'rounded bg-amber-400 px-3 py-1.5 text-sm font-bold text-slate-950 hover:bg-amber-300';
      resolveButton.textContent = 'Confirm selected match(es)';
      resolveButton.addEventListener('click', async () => {
        setCapcutBusy(true);
        capcutStatus.textContent = 'Applying your choices to the read-only preview...';
        try {
          const updatedPreview = await postCapcutJson('/api/capcut/resolve', {
            preview_id: capcutPreview.preview_id,
            resolutions: resolutionSelects.map(({ srtIndex, select }) => ({
              number: project.number,
              srt_index: srtIndex,
              capcut_indices: JSON.parse(select.value)
            }))
          });
          capcutPreview = updatedPreview;
          renderCapcutPreview(updatedPreview);
        } catch (error) {
          capcutStatus.textContent = `Could not resolve matches: ${error.message}`;
        } finally {
          setCapcutBusy(false);
          updateCapcutApplyButton();
        }
      });
      const note = document.createElement('span');
      note.className = 'ml-2 text-xs text-slate-300';
      note.textContent = 'Preview only; no project file is changed.';
      resolveItem.append(resolveButton, note);
      resolvePanel.appendChild(resolveItem);
      detailCell.appendChild(resolvePanel);
    }
    (project.unmatched_capcut || []).forEach((subtitle) => {
      const item = document.createElement('li');
      item.className = 'text-amber-200';
      item.textContent = `Extra CapCut #${subtitle.index} stays unchanged (${formatCapcutTime(subtitle.start)}–${formatCapcutTime(subtitle.end)}): ${subtitle.text}`;
      detailList.appendChild(item);
    });
    [...project.warnings, ...project.blockers].forEach((warning) => {
      const item = document.createElement('li');
      item.className = project.blockers.includes(warning) ? 'text-rose-300' : 'text-amber-200';
      item.textContent = warning;
      detailList.appendChild(item);
    });
    if (detailList.childElementCount) {
      const details = document.createElement('details');
      details.className = 'mt-1';
      const summary = document.createElement('summary');
      summary.className = 'cursor-pointer text-slate-400 hover:text-white';
      summary.textContent = 'Review text matches and warnings';
      details.append(summary, detailList);
      detailCell.appendChild(details);
    }

    row.append(selectCell, projectCell, textCell, detailCell);
    capcutProjectsList.appendChild(row);
  });

  capcutProjectsPanel.classList.toggle('hidden', data.projects.length === 0);
  capcutStatus.textContent = data.summary.eligible
    ? `Preview complete. ${data.summary.eligible} project(s) are eligible; review details before applying.`
    : 'Preview complete. No projects are eligible with the current safety options.';
  updateCapcutApplyButton();
}

function updateCapcutApplyButton() {
  const selected = capcutProjectsList.querySelectorAll('.capcut-project-select:checked:not(:disabled)');
  setCapcutApplyEnabled(Boolean(capcutPreview && selected.length && !capcutBusy));
}

function setCapcutBusy(busy) {
  capcutBusy = busy;
  btnCapcutPreview.disabled = busy;
  capcutInputs.forEach((input) => {
    input.disabled = busy;
  });
  capcutProjectsList.querySelectorAll('.capcut-project-select').forEach((checkbox) => {
    const project = capcutPreview?.projects.find((item) => item.number === checkbox.value);
    checkbox.disabled = busy || !project?.eligible;
  });
}

async function postCapcutJson(url, payload) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Request failed.');
  return data;
}

btnCapcutPreview.addEventListener('click', async () => {
  const projectsDir = capcutProjectsDir.value.trim();
  const srtDir = capcutSrtDir.value.trim();
  if (!projectsDir || !srtDir) {
    capcutStatus.textContent = 'Enter both folder paths before previewing.';
    return;
  }
  capcutPreview = null;
  setCapcutBusy(true);
  setCapcutApplyEnabled(false);
  capcutStatus.textContent = 'Scanning CapCut projects and matching Arabic SRT files...';
  capcutProjectsPanel.classList.add('hidden');
  capcutSummary.classList.add('hidden');
  capcutIssues.classList.add('hidden');
  try {
    const data = await postCapcutJson('/api/capcut/preview', {
      projects_dir: projectsDir,
      srt_dir: srtDir,
      allow_overlaps: true,
      extend_project_duration: true
    });
    renderCapcutPreview(data);
  } catch (error) {
    clearCapcutPreview(`Preview failed: ${error.message}`);
    capcutStatus.textContent = `Preview failed: ${error.message}`;
  } finally {
    setCapcutBusy(false);
    updateCapcutApplyButton();
  }
});

btnCapcutApply.addEventListener('click', async () => {
  if (!capcutPreview) return;
  const selected = [...capcutProjectsList.querySelectorAll('.capcut-project-select:checked:not(:disabled)')];
  const numbers = selected.map((checkbox) => checkbox.value);
  if (!numbers.length) {
    capcutStatus.textContent = 'Select at least one eligible project.';
    return;
  }
  const clipCount = selected.reduce((total, checkbox) => {
    const project = capcutPreview.projects.find((item) => item.number === checkbox.value);
    return total + (project?.subtitle_counts.matched_capcut_clips || 0);
  }, 0);
  const confirmed = window.confirm(
    `Apply SRT timing to ${clipCount} CapCut clip(s) across ${numbers.length} project(s)?\n\n` +
    'This directly updates each selected draft_content.json without creating a backup. ' +
    'Unmatched CapCut subtitle clips remain unchanged. Review all overlap and duration warnings before continuing.'
  );
  if (!confirmed) return;

  setCapcutBusy(true);
  setCapcutApplyEnabled(false);
  capcutStatus.textContent = 'Applying timing updates...';
  try {
    const result = await postCapcutJson('/api/capcut/apply', {
      preview_id: capcutPreview.preview_id,
      selected_numbers: numbers
    });
    const completed = result.updated.map((item) =>
      `${item.project_name}: updated ${item.updated_clips} CapCut clip(s) for ${item.updated_subtitles} SRT subtitle(s); no backup created`
    );
    const failures = (result.errors || []).map((item) =>
      `${item.project_name}: update failed — ${item.message}`
    );
    capcutPreview = null;
    capcutProjectsList.querySelectorAll('.capcut-project-select').forEach((checkbox) => {
      checkbox.disabled = true;
    });
    capcutStatus.textContent = failures.length
      ? `Update partially complete: ${result.updated.length} project(s) updated; ${failures.length} failed. Run a new preview before retrying.`
      : `Update complete: ${result.updated.length} project(s) updated. Run a new preview before any further update.`;
    capcutIssues.replaceChildren();
    [...completed, ...failures].forEach((line) => {
      const item = document.createElement('p');
      item.className = 'mb-1 last:mb-0';
      item.textContent = line;
      capcutIssues.appendChild(item);
    });
    capcutIssues.classList.toggle('hidden', completed.length + failures.length === 0);
  } catch (error) {
    clearCapcutPreview(`Apply failed: ${error.message}`);
    capcutStatus.textContent = `Apply failed: ${error.message} Run Preview again before retrying.`;
  } finally {
    setCapcutBusy(false);
    setCapcutApplyEnabled(false);
  }
});

[capcutProjectsDir, capcutSrtDir].forEach((input) => {
  input.addEventListener('input', () => clearCapcutPreview());
});

// =========================================================================
// Quran SRT Generator
// =========================================================================

const btnLoadGeneratorOptions = document.getElementById('btnLoadGeneratorOptions');
const btnStartGenerator = document.getElementById('btnStartGenerator');
const generatorSurah = document.getElementById('generatorSurah');
const generatorReciter = document.getElementById('generatorReciter');
const generatorTranslation = document.getElementById('generatorTranslation');
const generatorDownloadAudio = document.getElementById('generatorDownloadAudio');
const generatorCleanTranslation = document.getElementById('generatorCleanTranslation');
const generatorAddNumbers = document.getElementById('generatorAddNumbers');
const generatorOptionsStatus = document.getElementById('generatorOptionsStatus');
const generatorOutputRoot = document.getElementById('generatorOutputRoot');
const generatorStatus = document.getElementById('generatorStatus');
const generatorProgressPanel = document.getElementById('generatorProgressPanel');
const generatorProgressText = document.getElementById('generatorProgressText');
const generatorProgressCount = document.getElementById('generatorProgressCount');
const generatorProgressBar = document.getElementById('generatorProgressBar');
const generatorLog = document.getElementById('generatorLog');
let generatorOptionsLoaded = false;
let generatorJobId = null;
let generatorLoadingOptions = false;
let generatorRunning = false;

for (let surahNumber = 1; surahNumber <= 114; surahNumber += 1) {
  const option = document.createElement('option');
  option.value = String(surahNumber);
  option.textContent = `Surah ${surahNumber}`;
  generatorSurah.appendChild(option);
}
const allSurahsOption = document.createElement('option');
allSurahsOption.value = 'all';
allSurahsOption.textContent = 'All surahs (1–114)';
generatorSurah.appendChild(allSurahsOption);

function setGeneratorBusy(busy) {
  generatorRunning = busy;
  btnStartGenerator.disabled = busy || !generatorOptionsLoaded;
  btnStartGenerator.classList.toggle('bg-sky-600', !busy && generatorOptionsLoaded);
  btnStartGenerator.classList.toggle('hover:bg-sky-500', !busy && generatorOptionsLoaded);
  btnStartGenerator.classList.toggle('text-white', !busy && generatorOptionsLoaded);
  btnStartGenerator.classList.toggle('bg-slate-800', busy || !generatorOptionsLoaded);
  btnStartGenerator.classList.toggle('text-slate-500', busy || !generatorOptionsLoaded);
  btnStartGenerator.classList.toggle('cursor-not-allowed', busy || !generatorOptionsLoaded);
  [
    generatorSurah,
    generatorReciter,
    generatorTranslation,
    generatorDownloadAudio,
    generatorCleanTranslation,
    generatorAddNumbers
  ].forEach((control) => {
    control.disabled = busy || (control !== generatorSurah && !generatorOptionsLoaded);
  });
  btnLoadGeneratorOptions.disabled = busy || generatorLoadingOptions;
}

function setSelectOptions(select, placeholder, options) {
  select.replaceChildren();
  const initial = document.createElement('option');
  initial.value = '';
  initial.textContent = placeholder;
  initial.disabled = true;
  initial.selected = true;
  select.appendChild(initial);
  options.forEach(({ value, label }) => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  });
}

async function loadGeneratorOptions(forceRefresh = false) {
  if (generatorLoadingOptions || generatorRunning) return;
  generatorLoadingOptions = true;
  btnLoadGeneratorOptions.disabled = true;
  generatorOptionsStatus.textContent = 'Loading choices from Quran.com...';
  try {
    const suffix = forceRefresh ? '?refresh=true' : '';
    const response = await fetch(`/api/quran-generator/options${suffix}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Could not load generator choices.');

    const oldReciter = generatorReciter.value;
    setSelectOptions(
      generatorReciter,
      'Choose a reciter',
      data.reciters.map((reciter) => ({
        value: String(reciter.id),
        label: `${reciter.name}${reciter.style ? ` (${reciter.style})` : ''} — ID ${reciter.id}`
      }))
    );
    setSelectOptions(
      generatorTranslation,
      'Choose a translation',
      data.translations.map((translation) => ({
        value: String(translation.id),
        label: `${translation.name}${translation.language ? ` — ${translation.language}` : ''}`
      }))
    );
    if ([...generatorReciter.options].some((option) => option.value === oldReciter)) {
      generatorReciter.value = oldReciter;
    } else if ([...generatorReciter.options].some((option) => option.value === '7')) {
      generatorReciter.value = '7';
    }
    generatorTranslation.value = String(data.default_translation_id);
    generatorOutputRoot.textContent = data.output_root;
    generatorOptionsLoaded = true;
    generatorOptionsStatus.textContent =
      `Loaded ${data.reciters.length} reciters and ${data.translations.length} translations.`;
  } catch (error) {
    generatorOptionsLoaded = false;
    generatorOptionsStatus.textContent = `Could not load choices: ${error.message}`;
  } finally {
    generatorLoadingOptions = false;
    setGeneratorBusy(generatorRunning);
  }
}

async function pollGeneratorJob(jobId) {
  while (generatorJobId === jobId) {
    try {
      const response = await fetch(`/api/quran-generator/status/${encodeURIComponent(jobId)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Could not read generation status.');
      const percent = data.total
        ? Math.round((data.completed / data.total) * 100)
        : 0;
      generatorProgressCount.textContent = `${data.completed} / ${data.total}`;
      generatorProgressBar.style.width = `${percent}%`;
      generatorProgressText.textContent = data.current_surah
        ? `Generating Surah ${data.current_surah}...`
        : `${data.status[0].toUpperCase()}${data.status.slice(1)}`;
      generatorLog.textContent = data.log.join('\n');
      generatorLog.scrollTop = generatorLog.scrollHeight;
      if (data.output_root) generatorOutputRoot.textContent = data.output_root;

      if (['completed', 'partial', 'failed'].includes(data.status)) {
        const failures = data.failures.length;
        if (data.status === 'completed') {
          generatorStatus.textContent =
            `Generation complete: ${data.succeeded} surah(s) generated.`;
        } else if (data.status === 'partial') {
          generatorStatus.textContent =
            `Generation partially complete: ${data.succeeded} succeeded; ${failures} failed.`;
        } else {
          generatorStatus.textContent =
            `Generation failed: ${failures ? data.failures[0].message : 'see the log for details.'}`;
        }
        generatorStatus.className = `text-xs ${data.status === 'completed' ? 'text-emerald-400' : 'text-amber-300'}`;
        generatorJobId = null;
        setGeneratorBusy(false);
        return;
      }
    } catch (error) {
      generatorStatus.textContent = `Waiting for generation status: ${error.message}`;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1200));
  }
}

btnLoadGeneratorOptions.addEventListener('click', () => loadGeneratorOptions(true));
generatorTab.addEventListener('click', () => {
  if (!generatorOptionsLoaded) loadGeneratorOptions();
});

btnStartGenerator.addEventListener('click', async () => {
  if (!generatorOptionsLoaded || generatorRunning) return;
  if (!generatorReciter.value || !generatorTranslation.value) {
    generatorStatus.textContent = 'Choose a reciter and translation before generating.';
    return;
  }
  const allSurahs = generatorSurah.value === 'all';
  const surahDescription = allSurahs ? 'all 114 surahs' : `Surah ${generatorSurah.value}`;
  const output = generatorOutputRoot.textContent;
  const confirmed = window.confirm(
    `Generate ${surahDescription} using the selected reciter and translation?\n\n` +
    `Output root: ${output}\n` +
    'Existing CSV/SRT files with the same names will be overwritten without backups. ' +
    'Existing audio files will be skipped. Continue?'
  );
  if (!confirmed) return;

  generatorProgressPanel.classList.remove('hidden');
  generatorProgressBar.style.width = '0%';
  generatorProgressCount.textContent = '0 / 0';
  generatorLog.textContent = '';
  generatorStatus.className = 'text-xs text-slate-400';
  generatorStatus.textContent = 'Starting generator...';
  setGeneratorBusy(true);
  try {
    const job = await postCapcutJson('/api/quran-generator/start', {
      surah: allSurahs ? null : Number(generatorSurah.value),
      all_surahs: allSurahs,
      reciter_id: Number(generatorReciter.value),
      translation_id: Number(generatorTranslation.value),
      download_audio: generatorDownloadAudio.checked,
      clean_translation: generatorCleanTranslation.checked,
      add_numbers: generatorAddNumbers.checked
    });
    generatorJobId = job.job_id;
    generatorOutputRoot.textContent = job.output_root || generatorOutputRoot.textContent;
    generatorStatus.textContent = 'Generator started...';
    await pollGeneratorJob(job.job_id);
  } catch (error) {
    generatorStatus.className = 'text-xs text-rose-300';
    generatorStatus.textContent = `Could not start generator: ${error.message}`;
    setGeneratorBusy(false);
  }
});
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
      if (pct === 85) progressStatus.textContent = "Refining acoustic boundaries & applying subtitle timing adjustments...";
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
