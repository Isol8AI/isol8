#!/usr/bin/env node
/**
 * ora-availability-merger.js
 *
 * Pure compute. Takes event lists already fetched by the pipeline via
 * openclaw.invoke on gog / ms365 / calctl / caldav-calendar (all deterministic
 * API calls) and merges them into a unified non-overlapping busy set.
 * Finds free slots against that set within working hours. Checks a
 * specific slot for conflicts.
 *
 * The script never makes API calls itself — it's pure compute over
 * event data the pipeline fetched upstream.
 *
 * Zero LLM. Zero external dependencies.
 *
 * Modes:
 *   merge_busy       — {events_by_source} → unified non-overlapping busy intervals
 *   find_free_slots  — {busy_intervals, working_hours, duration_minutes, …} → slots
 *   check_slot       — {slot, busy_intervals} → {available, conflicts}
 */

function toMs(iso) {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : d.getTime();
}

function mergeBusyMode(input) {
  const eventsBySource = input.events_by_source || {};
  const rawIntervals = [];
  for (const [source, events] of Object.entries(eventsBySource)) {
    if (!Array.isArray(events)) continue;
    for (const e of events) {
      const startMs = toMs(e.start);
      const endMs = toMs(e.end);
      if (startMs == null || endMs == null || endMs <= startMs) continue;
      if (e.is_all_day && !input.block_all_day) continue;
      rawIntervals.push({
        start: startMs,
        end: endMs,
        source,
        title: e.title || '(untitled)',
        is_focus_block: !!e.is_focus_block,
        event_id: e.event_id || e.id || null,
        calendar_id: e.calendar_id || null,
      });
    }
  }
  rawIntervals.sort((a, b) => a.start - b.start);

  /** @type {Array<{start:number,end:number,title:string,is_focus_block:boolean,calendar_id:string|null,sources:string[],contributing_events:Array<{title:string,event_id:any,source:string}>}>} */
  const merged = [];
  for (const iv of rawIntervals) {
    const last = merged[merged.length - 1];
    if (last && iv.start <= last.end) {
      last.end = Math.max(last.end, iv.end);
      if (!last.sources.includes(iv.source)) last.sources.push(iv.source);
      last.contributing_events.push({
        title: iv.title,
        event_id: iv.event_id,
        source: iv.source,
      });
    } else {
      merged.push({
        start: iv.start,
        end: iv.end,
        title: iv.title,
        is_focus_block: iv.is_focus_block,
        calendar_id: iv.calendar_id,
        sources: [iv.source],
        contributing_events: [{
          title: iv.title,
          event_id: iv.event_id,
          source: iv.source,
        }],
      });
    }
  }

  return {
    busy_intervals: merged.map(iv => ({
      start: new Date(iv.start).toISOString(),
      end: new Date(iv.end).toISOString(),
      duration_minutes: Math.round((iv.end - iv.start) / 60000),
      title: iv.title,
      sources: iv.sources,
      is_focus_block: iv.is_focus_block,
      contributing_events: iv.contributing_events,
    })),
    total_intervals: merged.length,
    raw_event_count: rawIntervals.length,
  };
}

function wallClockToUtcMs(year, month, day, hour, minute, timeZone) {
  const guessUtcMs = Date.UTC(year, month - 1, day, hour, minute);
  const guessDate = new Date(guessUtcMs);
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone, timeZoneName: 'shortOffset',
  });
  const parts = fmt.formatToParts(guessDate);
  const offsetPart = parts.find(p => p.type === 'timeZoneName');
  const m = offsetPart?.value.match(/GMT(?:([+-])(\d{1,2})(?::(\d{2}))?)?/);
  if (!m || !m[1]) return guessUtcMs;
  const sign = m[1] === '-' ? -1 : 1;
  const off = sign * (parseInt(m[2], 10) * 60 + parseInt(m[3] || '0', 10));
  return guessUtcMs - off * 60 * 1000;
}

function buildSlot(startMs, endMs, timezone) {
  const start = new Date(startMs);
  const end = new Date(endMs);
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    weekday: 'short', month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit', hour12: true,
  });
  return {
    start: start.toISOString(),
    end: end.toISOString(),
    duration_minutes: Math.round((endMs - startMs) / 60000),
    formatted: fmt.format(start),
    timezone,
  };
}

function findFreeSlotsMode(input) {
  const busy = (input.busy_intervals || [])
    .map(iv => ({ start: toMs(iv.start), end: toMs(iv.end) }))
    .filter(iv => iv.start != null && iv.end != null)
    .sort((a, b) => a.start - b.start);

  const durationMinutes = Number(input.duration_minutes || 30);
  const durationMs = durationMinutes * 60 * 1000;
  const bufferMinutes = Number(input.buffer_minutes || 0);
  const bufferMs = bufferMinutes * 60 * 1000;
  const timezone = input.timezone || 'UTC';

  const working = input.working_hours || {};
  const workStartStr = working.start || '09:00';
  const workEndStr = working.end || '18:00';
  const [wsH, wsM] = workStartStr.split(':').map(Number);
  const [weH, weM] = workEndStr.split(':').map(Number);

  const rangeStart = input.range_start ? toMs(input.range_start) : Date.now();
  const rangeEnd = input.range_end
    ? toMs(input.range_end)
    : rangeStart + 14 * 24 * 60 * 60 * 1000;
  if (!rangeStart || !rangeEnd || rangeEnd <= rangeStart) {
    return { error: 'invalid range_start/range_end' };
  }

  const maxResults = Number(input.max_results || 10);
  const slots = [];

  const dayMs = 24 * 60 * 60 * 1000;
  const oneDay = Math.ceil((rangeEnd - rangeStart) / dayMs) + 1;
  for (let dayOffset = 0; dayOffset < oneDay && slots.length < maxResults; dayOffset++) {
    const dayStartUtc = rangeStart + dayOffset * dayMs;
    const dayDate = new Date(dayStartUtc);
    const dayBoundaryStr = new Intl.DateTimeFormat('en-CA', {
      timeZone: timezone,
      year: 'numeric', month: '2-digit', day: '2-digit',
    }).format(dayDate);
    const [yStr, mStr, dStr] = dayBoundaryStr.split('-');
    const y = parseInt(yStr, 10);
    const mo = parseInt(mStr, 10);
    const d = parseInt(dStr, 10);

    const windowStart = wallClockToUtcMs(y, mo, d, wsH, wsM || 0, timezone);
    const windowEnd = wallClockToUtcMs(y, mo, d, weH, weM || 0, timezone);
    if (windowEnd <= windowStart) continue;

    if (input.no_meeting_days) {
      const weekday = new Intl.DateTimeFormat('en-US', {
        timeZone: timezone, weekday: 'long',
      }).format(new Date(windowStart));
      if (input.no_meeting_days.includes(weekday)) continue;
    }

    let cursor = Math.max(windowStart, rangeStart);
    const windowBusy = busy.filter(iv => iv.end > windowStart && iv.start < windowEnd);
    for (const iv of windowBusy) {
      if (iv.start - cursor >= durationMs + 2 * bufferMs) {
        const slotStart = cursor + bufferMs;
        const slotEnd = slotStart + durationMs;
        if (slotEnd <= iv.start - bufferMs) {
          slots.push(buildSlot(slotStart, slotEnd, timezone));
          if (slots.length >= maxResults) break;
        }
      }
      cursor = Math.max(cursor, iv.end);
    }
    if (slots.length < maxResults && windowEnd - cursor >= durationMs + 2 * bufferMs) {
      const slotStart = cursor + bufferMs;
      const slotEnd = slotStart + durationMs;
      if (slotEnd <= windowEnd) {
        slots.push(buildSlot(slotStart, slotEnd, timezone));
      }
    }
  }

  return {
    free_slots: slots,
    count: slots.length,
    search_range: {
      start: new Date(rangeStart).toISOString(),
      end: new Date(rangeEnd).toISOString(),
    },
    duration_minutes: durationMinutes,
    timezone,
  };
}

function checkSlotMode(input) {
  const slot = input.slot;
  if (!slot || !slot.start || !slot.end) return { error: 'slot.start and slot.end required' };
  const start = toMs(slot.start);
  const end = toMs(slot.end);
  if (start == null || end == null || end <= start) return { error: 'invalid slot' };
  const ownEventId = slot.event_id || null;

  const conflicts = [];
  for (const iv of input.busy_intervals || []) {
    const ivStart = toMs(iv.start);
    const ivEnd = toMs(iv.end);
    if (ivStart == null || ivEnd == null) continue;
    if (iv.event_id && iv.event_id === ownEventId) continue;
    if (ivStart < end && ivEnd > start) {
      conflicts.push({
        start: iv.start,
        end: iv.end,
        title: iv.title,
        sources: iv.sources || [iv.source],
        is_focus_block: iv.is_focus_block || false,
      });
    }
  }

  return {
    available: conflicts.length === 0,
    conflicts,
    slot: { start: slot.start, end: slot.end },
  };
}

const MODES = {
  merge_busy: mergeBusyMode,
  find_free_slots: findFreeSlotsMode,
  check_slot: checkSlotMode,
};

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided\n');
    process.exit(1);
  }
  const mode = input.mode;
  if (!mode || !MODES[mode]) {
    process.stdout.write(JSON.stringify({
      ok: false,
      error: `unknown mode: ${mode}. Expected one of: ${Object.keys(MODES).join(', ')}`,
    }));
    process.exit(1);
  }
  const result = MODES[mode](input);
  if (result.error) {
    process.stdout.write(JSON.stringify({ ok: false, mode, ...result }));
    process.exit(1);
  }
  process.stdout.write(JSON.stringify({ ok: true, mode, ...result }));
}

function readStdin() {
  return new Promise((resolve) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => { data += chunk; });
    process.stdin.on('end', () => {
      try { resolve(JSON.parse(data)); }
      catch { resolve(null); }
    });
    if (process.stdin.isTTY) resolve(null);
  });
}

module.exports = {
  mergeBusyMode,
  findFreeSlotsMode,
  checkSlotMode,
};

if (require.main === module) {
  main().catch(err => {
    process.stderr.write(err.message + '\n');
    process.exit(1);
  });
}
