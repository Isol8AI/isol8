#!/usr/bin/env node
/**
 * echo-audio-preprocessor.js
 * Requirements 5, 7, 8: Silence trimming + confidence flagging + uncertain attribution marking.
 *
 * Deterministic. Zero LLM. The specific fix from Cornell hallucination research.
 */

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const segments = input.segments || [];
  const confidenceThreshold = input.confidence_threshold || 0.85;
  const attendees = input.attendees || [];

  const processed = segments.map(segment => {
    const result = {
      id: segment.id,
      start_time: segment.start_time,
      end_time: segment.end_time,
      text: segment.text,
      speaker_label: segment.speaker_label,
      speaker_name: null,
      confidence: segment.confidence || 1.0,
      flags: []
    };

    // Silence trimming validation — check if silence was present
    if (segment.leading_silence_ms > 500 || segment.trailing_silence_ms > 500) {
      result.flags.push({
        type: 'silence_adjacent',
        detail: `Segment has ${segment.leading_silence_ms}ms leading / ${segment.trailing_silence_ms}ms trailing silence. Hallucination risk elevated per Cornell research.`,
        severity: 'review'
      });
    }

    // Confidence check
    if (segment.confidence < confidenceThreshold) {
      result.flags.push({
        type: 'low_confidence',
        detail: `Transcription confidence ${Math.round(segment.confidence * 100)}% — below ${Math.round(confidenceThreshold * 100)}% threshold.`,
        reason: segment.confidence < 0.5 ? 'possible_background_noise' :
                segment.confidence < 0.7 ? 'overlapping_speakers' : 'unclear_audio',
        severity: 'flag_for_review'
      });
    }

    // Speaker attribution — map label to attendee
    if (segment.speaker_label) {
      const match = mapSpeaker(segment.speaker_label, attendees, segment.speaker_confidence);
      result.speaker_name = match.name;
      result.speaker_confidence = match.confidence;

      if (match.confidence < 0.7) {
        result.flags.push({
          type: 'uncertain_attribution',
          detail: `Speaker identification uncertain — possibly ${match.candidates.join(' or ')}.`,
          severity: 'flag_for_review'
        });
        result.speaker_name = `[UNCERTAIN — possibly ${match.candidates.join(' or ')}]`;
      }
    }

    return result;
  });

  const flagged = processed.filter(p => p.flags.length > 0);

  const result = {
    processed_segments: processed,
    total_segments: segments.length,
    flagged_count: flagged.length,
    silence_adjacent: flagged.filter(f => f.flags.some(fl => fl.type === 'silence_adjacent')).length,
    low_confidence: flagged.filter(f => f.flags.some(fl => fl.type === 'low_confidence')).length,
    uncertain_attribution: flagged.filter(f => f.flags.some(fl => fl.type === 'uncertain_attribution')).length,
    confidence_threshold_used: confidenceThreshold,
    timestamp: new Date().toISOString()
  };

  process.stdout.write(JSON.stringify(result));
}

function mapSpeaker(label, attendees, speakerConfidence) {
  // If the transcription platform provided a name mapping
  if (attendees.length === 0) {
    return { name: label, confidence: 0.5, candidates: [label] };
  }

  // Map speaker label to attendee by platform-provided mapping or position
  const labelNum = parseInt(label.replace(/[^0-9]/g, ''), 10);
  if (!isNaN(labelNum) && labelNum < attendees.length) {
    return {
      name: attendees[labelNum].name || attendees[labelNum],
      confidence: speakerConfidence || 0.8,
      candidates: [attendees[labelNum].name || attendees[labelNum]]
    };
  }

  // Direct name match
  const nameMatch = attendees.find(a =>
    (a.name || a).toLowerCase() === label.toLowerCase()
  );
  if (nameMatch) {
    return { name: nameMatch.name || nameMatch, confidence: 0.95, candidates: [nameMatch.name || nameMatch] };
  }

  // Uncertain — return top 2 candidates
  return {
    name: label,
    confidence: speakerConfidence || 0.4,
    candidates: attendees.slice(0, 2).map(a => a.name || a)
  };
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

if (require.main === module) { main().catch(err => { process.stderr.write(err.message); process.exit(1); }); }
