#!/usr/bin/env node
/**
 * echo-transcript-normalizer.js
 * Converts provider-specific transcript responses (Zoom Cloud Recording API,
 * Google Meet captions via Drive, Microsoft Teams via Graph) into the
 * canonical segment shape that echo-audio-preprocessor.js consumes.
 *
 * Deterministic. Zero LLM. Zero external dependencies.
 */

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  let segments = [];
  let source = null;

  if (isPopulated(input.zoom)) {
    segments = normalizeZoom(input.zoom);
    source = 'zoom';
  } else if (isPopulated(input.gmeet)) {
    segments = normalizeGmeet(input.gmeet);
    source = 'gmeet';
  } else if (isPopulated(input.teams)) {
    segments = normalizeTeams(input.teams);
    source = 'teams';
  }

  process.stdout.write(JSON.stringify({
    segments,
    source,
    total_segments: segments.length,
    timestamp: new Date().toISOString()
  }));
}

function isPopulated(raw) {
  if (!raw) return false;
  if (Array.isArray(raw) && raw.length === 0) return false;
  if (typeof raw === 'object' && Object.keys(raw).length === 0) return false;
  return true;
}

function normalizeZoom(raw) {
  const utterances = raw?.transcript?.utterances || raw?.utterances || [];
  return utterances.map((u, i) => ({
    id: u.id || `zoom_${i}`,
    start_time: toSeconds(u.start_time ?? u.start),
    end_time: toSeconds(u.end_time ?? u.end),
    text: u.text || '',
    speaker_label: u.speaker || u.speaker_name || null,
    speaker_confidence: u.speaker_confidence ?? null,
    confidence: u.confidence ?? 1.0,
    leading_silence_ms: u.leading_silence_ms || 0,
    trailing_silence_ms: u.trailing_silence_ms || 0
  }));
}

function normalizeGmeet(raw) {
  const captions = raw?.captions || raw?.entries || [];
  return captions.map((c, i) => ({
    id: c.id || `gmeet_${i}`,
    start_time: toSeconds(c.startOffset ?? c.start),
    end_time: toSeconds(c.endOffset ?? c.end),
    text: c.text || c.caption || '',
    speaker_label: c.displayName || c.speaker || null,
    speaker_confidence: null,
    confidence: 1.0,
    leading_silence_ms: 0,
    trailing_silence_ms: 0
  }));
}

function normalizeTeams(raw) {
  const entries = raw?.entries || raw?.transcriptEntries || [];
  return entries.map((e, i) => ({
    id: e.id || `teams_${i}`,
    start_time: toSeconds(e.startDateTime ?? e.start ?? e.offset),
    end_time: toSeconds(e.endDateTime ?? e.end),
    text: e.text || e.content || '',
    speaker_label: e.speakerDisplayName || e.speaker?.displayName || null,
    speaker_confidence: null,
    confidence: 1.0,
    leading_silence_ms: 0,
    trailing_silence_ms: 0
  }));
}

function toSeconds(value) {
  if (value == null) return 0;
  if (typeof value === 'number') return value;
  const str = String(value);
  const hms = str.match(/^(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d+))?$/);
  if (hms) {
    return parseInt(hms[1]) * 3600 + parseInt(hms[2]) * 60 + parseInt(hms[3])
      + (hms[4] ? parseFloat('0.' + hms[4]) : 0);
  }
  const iso = str.match(/^PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$/);
  if (iso) {
    return (parseInt(iso[1] || '0') * 60) + parseFloat(iso[2] || '0');
  }
  const num = parseFloat(str);
  return isNaN(num) ? 0 : num;
}

function readStdin() {
  return new Promise((resolve) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => data += chunk);
    process.stdin.on('end', () => { try { resolve(JSON.parse(data)); } catch { resolve(null); } });
    if (process.stdin.isTTY) resolve(null);
  });
}

module.exports = { normalizeZoom, normalizeGmeet, normalizeTeams, toSeconds };

if (require.main === module) { main().catch(err => { process.stderr.write(err.message); process.exit(1); }); }
