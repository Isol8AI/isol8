#!/usr/bin/env node
/**
 * ora-booking-engine.js
 *
 * Pure compute — builds provider-specific API payloads for the calendar
 * skill (gog / ms365 / calctl / caldav-calendar) that the pipeline will
 * invoke. The script itself never makes HTTP calls; the actual calendar
 * write is a subsequent openclaw.invoke step in the lobster pipeline,
 * using the payload this script returns.
 *
 * Single-phase booking with post-hoc conflict verification. Every
 * mainstream scheduler (Calendly, Cal.com, Google Calendar itself) uses
 * single-phase booking + post-write conflict check. The script supports
 * rollback when verify_booking returns conflicts.
 *
 * Zero LLM. Zero external dependencies.
 *
 * Modes:
 *   prepare_booking    — {slot, participants, meeting_type, user_calendar} → {provider, action, args}
 *   verify_booking     — {event_id, slot, fresh_busy_intervals} → {confirmed, conflicts}
 *   prepare_reschedule — {existing_event, new_slot, user_calendar} → {provider, action, args}
 *   prepare_cancel     — {existing_event, user_calendar} → {provider, action, args}
 */

const PROVIDER_MAP = {
  google: 'gog',
  gcal: 'gog',
  gmail: 'gog',
  outlook: 'ms365',
  office365: 'ms365',
  ms365: 'ms365',
  apple: 'calctl',
  icloud: 'caldav-calendar',
  caldav: 'caldav-calendar',
  fastmail: 'caldav-calendar',
  nextcloud: 'caldav-calendar',
};

function providerSkill(calendarPlatform) {
  const key = String(calendarPlatform || 'google').toLowerCase();
  return PROVIDER_MAP[key] || 'gog';
}

function prepareBookingMode(input) {
  const slot = input.slot;
  if (!slot || !slot.start || !slot.end) {
    return { error: 'slot.start and slot.end required' };
  }
  const participants = input.participants || [];
  if (!Array.isArray(participants) || participants.length === 0) {
    return { error: 'at least one participant required' };
  }
  const userCalendar = input.user_calendar || {};
  const platform = userCalendar.platform || 'google';
  const provider = providerSkill(platform);
  const meetingType = input.meeting_type || 'meeting';
  const title = input.title || `${meetingType}: ${participants.map(p => p.name || p.email).join(', ')}`;
  const description = input.description || '';

  const attendees = participants
    .filter(p => p.email && p.email !== userCalendar.user_email)
    .map(p => ({
      email: p.email,
      name: p.name || null,
      optional: p.optional || false,
    }));

  const videoLinkRequested = input.add_video_link !== false;

  let action;
  let args;
  switch (provider) {
    case 'gog':
      action = 'calendar-create-event';
      args = {
        calendar_id: userCalendar.calendar_id || 'primary',
        title,
        description,
        start: slot.start,
        end: slot.end,
        attendees,
        conference_data_version: videoLinkRequested ? 1 : 0,
        send_updates: input.send_updates || 'all',
      };
      break;
    case 'ms365':
      action = 'calendar-create-event';
      args = {
        calendar_id: userCalendar.calendar_id || 'default',
        subject: title,
        body: { contentType: 'text', content: description },
        start: { dateTime: slot.start, timeZone: userCalendar.timezone || 'UTC' },
        end: { dateTime: slot.end, timeZone: userCalendar.timezone || 'UTC' },
        attendees: attendees.map(a => ({
          emailAddress: { address: a.email, name: a.name },
          type: a.optional ? 'optional' : 'required',
        })),
        isOnlineMeeting: videoLinkRequested,
        onlineMeetingProvider: 'teamsForBusiness',
      };
      break;
    case 'caldav-calendar':
    case 'calctl':
      action = 'create-event';
      args = {
        calendar: userCalendar.calendar_id || 'primary',
        title,
        description,
        start: slot.start,
        end: slot.end,
        attendees: attendees.map(a => a.email),
      };
      break;
    default:
      return { error: `unknown provider: ${provider}` };
  }

  return {
    provider,
    action,
    args,
    meta: {
      title,
      slot,
      participant_count: attendees.length,
      add_video_link: videoLinkRequested,
      send_updates: args.send_updates || null,
    },
  };
}

function verifyBookingMode(input) {
  const eventId = input.event_id;
  const slot = input.slot;
  if (!eventId) return { error: 'event_id required' };
  if (!slot || !slot.start || !slot.end) return { error: 'slot required' };

  const slotStart = new Date(slot.start).getTime();
  const slotEnd = new Date(slot.end).getTime();
  if (isNaN(slotStart) || isNaN(slotEnd)) return { error: 'invalid slot times' };

  const conflicts = [];
  for (const iv of input.fresh_busy_intervals || []) {
    const ivStart = new Date(iv.start).getTime();
    const ivEnd = new Date(iv.end).getTime();
    if (isNaN(ivStart) || isNaN(ivEnd)) continue;
    // Self-detection: skip if any contributing event has our event_id
    const contributingEventIds = new Set();
    if (iv.event_id) contributingEventIds.add(iv.event_id);
    for (const e of iv.contributing_events || []) {
      if (e.event_id) contributingEventIds.add(e.event_id);
    }
    if (contributingEventIds.has(eventId)) continue;
    // Belt-and-suspenders: if the interval's time range exactly matches
    // the booked slot (within 60s tolerance), it's almost certainly the
    // event we just created — skip it even if the event_id format differs
    // between create-response and list-response (e.g. recurring instance
    // suffixes on Google Calendar).
    if (Math.abs(ivStart - slotStart) < 60000 && Math.abs(ivEnd - slotEnd) < 60000) continue;
    if (ivStart < slotEnd && ivEnd > slotStart) {
      conflicts.push({
        start: iv.start,
        end: iv.end,
        title: iv.title,
        sources: iv.sources || [iv.source],
      });
    }
  }

  return {
    confirmed: conflicts.length === 0,
    conflicts,
    needs_rollback: conflicts.length > 0,
    event_id: eventId,
    slot,
  };
}

function prepareRescheduleMode(input) {
  const existing = input.existing_event;
  const newSlot = input.new_slot;
  if (!existing || !existing.event_id) return { error: 'existing_event.event_id required' };
  if (!newSlot || !newSlot.start || !newSlot.end) return { error: 'new_slot required' };

  const userCalendar = input.user_calendar || {};
  const provider = providerSkill(userCalendar.platform || 'google');

  let action, args;
  switch (provider) {
    case 'gog':
      action = 'calendar-update-event';
      args = {
        calendar_id: userCalendar.calendar_id || 'primary',
        event_id: existing.event_id,
        start: newSlot.start,
        end: newSlot.end,
        send_updates: input.send_updates || 'all',
      };
      break;
    case 'ms365':
      action = 'calendar-update-event';
      args = {
        event_id: existing.event_id,
        start: { dateTime: newSlot.start, timeZone: userCalendar.timezone || 'UTC' },
        end: { dateTime: newSlot.end, timeZone: userCalendar.timezone || 'UTC' },
      };
      break;
    case 'caldav-calendar':
    case 'calctl':
      action = 'update-event';
      args = {
        event_id: existing.event_id,
        start: newSlot.start,
        end: newSlot.end,
      };
      break;
    default:
      return { error: `unknown provider: ${provider}` };
  }

  return {
    provider,
    action,
    args,
    meta: {
      event_id: existing.event_id,
      from: { start: existing.start, end: existing.end },
      to: { start: newSlot.start, end: newSlot.end },
    },
  };
}

function prepareCancelMode(input) {
  const existing = input.existing_event;
  if (!existing || !existing.event_id) return { error: 'existing_event.event_id required' };

  const userCalendar = input.user_calendar || {};
  const provider = providerSkill(userCalendar.platform || 'google');

  let action, args;
  switch (provider) {
    case 'gog':
      action = 'calendar-delete-event';
      args = {
        calendar_id: userCalendar.calendar_id || 'primary',
        event_id: existing.event_id,
        send_updates: input.send_updates || 'all',
      };
      break;
    case 'ms365':
      action = 'calendar-delete-event';
      args = { event_id: existing.event_id };
      break;
    case 'caldav-calendar':
    case 'calctl':
      action = 'delete-event';
      args = { event_id: existing.event_id };
      break;
    default:
      return { error: `unknown provider: ${provider}` };
  }

  return {
    provider,
    action,
    args,
    meta: { event_id: existing.event_id, title: existing.title },
  };
}

const MODES = {
  prepare_booking: prepareBookingMode,
  verify_booking: verifyBookingMode,
  prepare_reschedule: prepareRescheduleMode,
  prepare_cancel: prepareCancelMode,
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
  providerSkill,
  prepareBookingMode,
  verifyBookingMode,
  prepareRescheduleMode,
  prepareCancelMode,
};

if (require.main === module) {
  main().catch(err => {
    process.stderr.write(err.message + '\n');
    process.exit(1);
  });
}
