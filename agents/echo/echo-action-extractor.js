#!/usr/bin/env node
/**
 * echo-action-extractor.js
 * Requirements 16, 17, 19: Extract action items from transcript with correct attribution.
 *
 * Deterministic attribution verification. Zero LLM (classification handled by commitment-classifier).
 */

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  const classifiedStatements = input.classified || [];
  const attendees = input.attendees || [];
  const meetingContext = input.meeting_context || {};

  const actionItems = [];
  const tentativeItems = [];
  const flagged = [];

  for (const stmt of classifiedStatements) {
    if (stmt.classification === 'not_action_item' || stmt.classification === 'declined') continue;

    // Requirement 19: Verify the assigned person is the SPEAKER, not merely mentioned
    const speaker = stmt.speaker;
    const mentionedNames = extractMentionedNames(stmt.text, attendees);
    const isSpeakerCommitting = !isOnlyMentioned(speaker, stmt.text, attendees);

    if (!isSpeakerCommitting) {
      // Someone said "we should ask Sarah about this" — Sarah is mentioned, not committing
      flagged.push({
        segment_id: stmt.segment_id,
        text: stmt.text,
        mentioned_person: speaker,
        actual_speaker: stmt.speaker,
        reason: `${speaker} was mentioned by another speaker, not speaking a commitment themselves. Not assigning as action item owner.`,
        timestamp: stmt.timestamp
      });
      continue;
    }

    // Extract deadline if present
    const deadline = extractDeadline(stmt.text);

    // Build the action item
    const item = {
      id: `ai_${stmt.segment_id}`,
      owner: speaker,
      task: stmt.text,
      deadline: deadline?.parsed || null,
      deadline_text: deadline?.raw || null,
      meeting_id: meetingContext.meeting_id,
      meeting_title: meetingContext.title,
      meeting_date: meetingContext.date,
      timestamp: stmt.timestamp,
      timestamp_link: `${meetingContext.recording_url}?t=${formatTimestamp(stmt.timestamp)}`,
      classification: stmt.classification,
      confidence: stmt.confidence
    };

    if (stmt.classification === 'definitive') {
      actionItems.push(item);
    } else if (stmt.classification === 'tentative') {
      item.display_label = 'FOR FOLLOW-UP / TO BE CONFIRMED';
      item.hedged_language = stmt.text;
      tentativeItems.push(item);
    } else if (stmt.classification === 'ambiguous') {
      item.display_label = 'NEEDS REVIEW — ambiguous commitment';
      tentativeItems.push(item);
    }

    // Check for mentioned names that might be action item owners via delegation
    for (const mentioned of mentionedNames) {
      if (mentioned !== speaker) {
        // "Sarah, can you handle the proposal?" — speaker is delegating TO Sarah
        const isDelegation = /can you|could you|would you|please|will you/.test(stmt.text.toLowerCase());
        if (isDelegation) {
          actionItems.push({
            ...item,
            id: `ai_delegated_${stmt.segment_id}`,
            owner: mentioned,
            delegated_by: speaker,
            task: stmt.text,
            note: `Delegated by ${speaker} during the meeting.`
          });
        }
      }
    }
  }

  const result = {
    action_items: actionItems,
    tentative_items: tentativeItems,
    flagged_attribution_issues: flagged,
    counts: {
      definitive: actionItems.filter(a => !a.delegated_by).length,
      delegated: actionItems.filter(a => a.delegated_by).length,
      tentative: tentativeItems.length,
      flagged: flagged.length
    },
    timestamp: new Date().toISOString()
  };

  process.stdout.write(JSON.stringify(result));
}

function extractMentionedNames(text, attendees) {
  const mentioned = [];
  for (const attendee of attendees) {
    const name = attendee.name || attendee;
    const firstName = name.split(' ')[0];
    if (text.toLowerCase().includes(firstName.toLowerCase())) {
      mentioned.push(name);
    }
  }
  return mentioned;
}

function isOnlyMentioned(speakerName, text, attendees) {
  // Check if the "speaker" was actually mentioned by someone else
  // This is a safety check — if speaker attribution is uncertain
  // and the name appears only in third person, flag it
  const lower = text.toLowerCase();
  const firstName = (speakerName || '').split(' ')[0].toLowerCase();

  const thirdPersonPatterns = [
    `ask ${firstName}`, `tell ${firstName}`, `${firstName} should`,
    `${firstName} could`, `${firstName} might`, `check with ${firstName}`,
    `${firstName} needs to`, `have ${firstName}`
  ];

  return thirdPersonPatterns.some(p => lower.includes(p));
}

function extractDeadline(text) {
  const lower = text.toLowerCase();
  const patterns = [
    { regex: /by (friday|monday|tuesday|wednesday|thursday|saturday|sunday)/i, type: 'day_of_week' },
    { regex: /by (end of week|eow|end of day|eod|cob)/i, type: 'relative' },
    { regex: /by (next week|next month|tomorrow)/i, type: 'relative' },
    { regex: /by (\d{1,2}\/\d{1,2})/i, type: 'date' },
    { regex: /by (january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}/i, type: 'date' },
    { regex: /within (\d+)\s+(days?|weeks?|hours?)/i, type: 'duration' }
  ];

  for (const { regex, type } of patterns) {
    const match = text.match(regex);
    if (match) {
      return { raw: match[0], parsed: match[0], type };
    }
  }

  return null;
}

function formatTimestamp(seconds) {
  if (!seconds) return '0';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}m${secs}s`;
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

module.exports = { extractMentionedNames, isOnlyMentioned, extractDeadline };

if (require.main === module) { main().catch(err => { process.stderr.write(err.message); process.exit(1); }); }
