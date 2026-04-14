#!/usr/bin/env node
/**
 * ora-datetime-engine.js
 *
 * Deterministic timezone-aware datetime math using Node stdlib Intl APIs.
 * DST-aware — offsets are computed per date, not per current moment. This
 * is the direct fix for the Berlin DST disaster class of bug.
 *
 * Zero external dependencies. Zero LLM. Pure compute.
 *
 * Modes:
 *   convert          — ISO timestamp + target tz → ISO in target tz (DST-aware)
 *   batch_convert    — many slots × many participants → per-participant local times
 *   resolve_relative — structured spec ({day_of_week, hour, relative}) → ISO
 *   add_duration     — ISO + minutes → ISO
 *   same_day         — two ISO timestamps + tz → bool
 *   day_of_week      — ISO + tz → weekday name
 *   working_hours    — ISO + tz + working hours range → bool + local hour
 *   tz_offset        — ISO + tz → signed minutes offset from UTC on that date
 *
 * Natural-language parsing is NOT in scope — that's an llm-task step in
 * the pipeline (thinking:"off") that emits structured fields, which this
 * script then resolves deterministically.
 */

// ──────────────────────────────────────────────────────────────
// Timezone primitives (Intl-based, DST-aware per-date)
// ──────────────────────────────────────────────────────────────

function offsetMinutes(date, timeZone) {
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone,
    timeZoneName: 'shortOffset',
  });
  const parts = formatter.formatToParts(date);
  const offsetPart = parts.find(p => p.type === 'timeZoneName');
  if (!offsetPart) return 0;
  const m = offsetPart.value.match(/GMT(?:([+-])(\d{1,2})(?::(\d{2}))?)?/);
  if (!m) return 0;
  if (!m[1]) return 0;
  const sign = m[1] === '-' ? -1 : 1;
  const hours = parseInt(m[2], 10);
  const minutes = parseInt(m[3] || '0', 10);
  return sign * (hours * 60 + minutes);
}

function toIsoWithOffset(date, timeZone) {
  const offset = offsetMinutes(date, timeZone);
  const localMs = date.getTime() + offset * 60 * 1000;
  const local = new Date(localMs);
  const yyyy = local.getUTCFullYear();
  const mm = String(local.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(local.getUTCDate()).padStart(2, '0');
  const hh = String(local.getUTCHours()).padStart(2, '0');
  const mi = String(local.getUTCMinutes()).padStart(2, '0');
  const ss = String(local.getUTCSeconds()).padStart(2, '0');
  const sign = offset >= 0 ? '+' : '-';
  const absOff = Math.abs(offset);
  const offH = String(Math.floor(absOff / 60)).padStart(2, '0');
  const offM = String(absOff % 60).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}T${hh}:${mi}:${ss}${sign}${offH}:${offM}`;
}

function wallClockToUtc(year, month, day, hour, minute, timeZone) {
  const guessUtcMs = Date.UTC(year, month - 1, day, hour, minute);
  const guessDate = new Date(guessUtcMs);
  let off = offsetMinutes(guessDate, timeZone);
  let correctedMs = guessUtcMs - off * 60 * 1000;
  const correctedDate = new Date(correctedMs);
  const off2 = offsetMinutes(correctedDate, timeZone);
  if (off2 !== off) {
    correctedMs = guessUtcMs - off2 * 60 * 1000;
  }
  return new Date(correctedMs);
}

function localHour(date, timeZone) {
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
  const parts = Object.fromEntries(fmt.formatToParts(date).map(p => [p.type, p.value]));
  return parseInt(parts.hour, 10) + parseInt(parts.minute, 10) / 60;
}

function formatHumanReadable(date, timeZone) {
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone,
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZoneName: 'short',
  });
  return fmt.format(date);
}

// ──────────────────────────────────────────────────────────────
// Modes
// ──────────────────────────────────────────────────────────────

function convertMode(input) {
  if (!input.iso_timestamp) return { error: 'iso_timestamp required' };
  if (!input.target_timezone) return { error: 'target_timezone required' };
  const date = new Date(input.iso_timestamp);
  if (isNaN(date.getTime())) return { error: `invalid iso_timestamp: ${input.iso_timestamp}` };
  return {
    original: input.iso_timestamp,
    converted: toIsoWithOffset(date, input.target_timezone),
    target_timezone: input.target_timezone,
    offset_minutes: offsetMinutes(date, input.target_timezone),
  };
}

function batchConvertMode(input) {
  const slots = input.slots || [];
  const participants = input.participants || [];
  if (!Array.isArray(slots) || !Array.isArray(participants)) {
    return { error: 'slots and participants must be arrays' };
  }
  const out = [];
  for (const slot of slots) {
    const start = new Date(slot.start);
    const end = slot.end ? new Date(slot.end) : null;
    if (isNaN(start.getTime())) continue;
    const participant_local_times = {};
    for (const p of participants) {
      const tz = p.timezone || p.tz;
      if (!tz || !p.email) continue;
      participant_local_times[p.email] = {
        start: toIsoWithOffset(start, tz),
        end: end ? toIsoWithOffset(end, tz) : null,
        hour: localHour(start, tz),
        formatted: formatHumanReadable(start, tz),
        timezone: tz,
      };
    }
    out.push({ ...slot, participant_local_times });
  }
  return { slots: out };
}

function resolveRelativeMode(input) {
  const {
    day_of_week,
    hour,
    minute = 0,
    relative = 'next',
    user_timezone,
    now: nowIso,
  } = input;
  if (!user_timezone) return { error: 'user_timezone required' };
  if (hour == null) return { error: 'hour required' };
  if (day_of_week == null) return { error: 'day_of_week required' };

  const dayNames = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'];
  const targetDow = typeof day_of_week === 'number'
    ? day_of_week
    : dayNames.indexOf(String(day_of_week).toLowerCase());
  if (targetDow < 0 || targetDow > 6) return { error: `invalid day_of_week: ${day_of_week}` };

  const now = nowIso ? new Date(nowIso) : new Date();
  if (isNaN(now.getTime())) return { error: `invalid now: ${nowIso}` };
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: user_timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    weekday: 'short',
  });
  const parts = Object.fromEntries(fmt.formatToParts(now).map(p => [p.type, p.value]));
  const nowYear = parseInt(parts.year, 10);
  const nowMonth = parseInt(parts.month, 10);
  const nowDay = parseInt(parts.day, 10);
  const nowDow = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(parts.weekday);

  let daysForward = (targetDow - nowDow + 7) % 7;
  if (daysForward === 0 && relative === 'next') daysForward = 7;
  if (daysForward === 0 && relative === 'this') daysForward = 0;

  const baseUtc = Date.UTC(nowYear, nowMonth - 1, nowDay);
  const targetUtc = baseUtc + daysForward * 24 * 60 * 60 * 1000;
  const targetDate = new Date(targetUtc);
  const targetY = targetDate.getUTCFullYear();
  const targetM = targetDate.getUTCMonth() + 1;
  const targetD = targetDate.getUTCDate();

  const resolved = wallClockToUtc(targetY, targetM, targetD, hour, minute, user_timezone);
  return {
    resolved_iso: toIsoWithOffset(resolved, user_timezone),
    resolved_utc: resolved.toISOString(),
    user_timezone,
    day_of_week: dayNames[targetDow],
  };
}

function addDurationMode(input) {
  const date = new Date(input.iso_timestamp);
  if (isNaN(date.getTime())) return { error: 'invalid iso_timestamp' };
  const minutes = Number(input.minutes);
  if (isNaN(minutes)) return { error: 'minutes must be a number' };
  const result = new Date(date.getTime() + minutes * 60 * 1000);
  const tz = input.timezone;
  return {
    start: input.iso_timestamp,
    end: tz ? toIsoWithOffset(result, tz) : result.toISOString(),
    added_minutes: minutes,
  };
}

function sameDayMode(input) {
  const a = new Date(input.a);
  const b = new Date(input.b);
  const tz = input.timezone;
  if (isNaN(a.getTime()) || isNaN(b.getTime())) return { error: 'invalid timestamps' };
  if (!tz) return { error: 'timezone required' };
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
  });
  return { same_day: fmt.format(a) === fmt.format(b) };
}

function dayOfWeekMode(input) {
  const date = new Date(input.iso_timestamp);
  if (isNaN(date.getTime())) return { error: 'invalid iso_timestamp' };
  const tz = input.timezone;
  if (!tz) return { error: 'timezone required' };
  const fmt = new Intl.DateTimeFormat('en-US', { timeZone: tz, weekday: 'long' });
  return { day_of_week: fmt.format(date) };
}

function workingHoursMode(input) {
  const date = new Date(input.iso_timestamp);
  if (isNaN(date.getTime())) return { error: 'invalid iso_timestamp' };
  const tz = input.timezone;
  if (!tz) return { error: 'timezone required' };
  const working = input.working_hours || {};
  const startStr = working.start || '09:00';
  const endStr = working.end || '18:00';
  const [sh, sm] = startStr.split(':').map(Number);
  const [eh, em] = endStr.split(':').map(Number);
  const localHourDec = localHour(date, tz);
  const startDec = sh + (sm || 0) / 60;
  const endDec = eh + (em || 0) / 60;
  return {
    within_hours: localHourDec >= startDec && localHourDec < endDec,
    local_hour: localHourDec,
    window: { start: startStr, end: endStr },
  };
}

function tzOffsetMode(input) {
  const date = new Date(input.iso_timestamp);
  if (isNaN(date.getTime())) return { error: 'invalid iso_timestamp' };
  const tz = input.timezone;
  if (!tz) return { error: 'timezone required' };
  return {
    offset_minutes: offsetMinutes(date, tz),
    timezone: tz,
    iso: toIsoWithOffset(date, tz),
  };
}

// ──────────────────────────────────────────────────────────────
// Entry point
// ──────────────────────────────────────────────────────────────

const MODES = {
  convert: convertMode,
  batch_convert: batchConvertMode,
  resolve_relative: resolveRelativeMode,
  add_duration: addDurationMode,
  same_day: sameDayMode,
  day_of_week: dayOfWeekMode,
  working_hours: workingHoursMode,
  tz_offset: tzOffsetMode,
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
  offsetMinutes,
  toIsoWithOffset,
  wallClockToUtc,
  convertMode,
  batchConvertMode,
  resolveRelativeMode,
  addDurationMode,
  sameDayMode,
  dayOfWeekMode,
  workingHoursMode,
  tzOffsetMode,
};

if (require.main === module) {
  main().catch(err => {
    process.stderr.write(err.message + '\n');
    process.exit(1);
  });
}
