#!/usr/bin/env node
/**
 * nexus-notify.js
 * Template renderer for Nexus's deterministic notifications.
 *
 * This is a pure function: given a template name + data, it loads the
 * template file from ./notifications/<template>.txt, substitutes placeholders,
 * and returns the rendered text. The .lobster pipeline takes the rendered
 * output and passes it to openclaw.invoke --tool slack --action post — that
 * way the slack integration stays in the openclaw tool layer (matching the
 * Pulse convention) and this script has no network access, no credentials,
 * no external coupling.
 *
 * Template syntax (minimal):
 *   {{var}}                  scalar substitution — looks up data[var]
 *   {{var|join:<sep>}}       join an array with the given separator
 *                            (literal pipe-escaped newlines: use \n in sep)
 *   {{var|default:<value>}}  fallback when the field is missing or empty
 *
 * Nested access uses dot paths: {{issue.title}}, {{primary.type}}.
 *
 * Deterministic. Zero LLM.
 *
 * Input (stdin JSON):
 *   { template: string, data: object }
 *
 * Output:
 *   {ok: true, template, text, char_count}
 *   {ok: false, reason}
 */

const fs = require('fs');
const path = require('path');
const { readStdin, ok, fail } = require('./paperclip-http');

const TEMPLATE_DIR = path.join(__dirname, 'notifications');

function getPath(obj, dotted) {
  if (obj == null) return undefined;
  const parts = dotted.split('.');
  let cur = obj;
  for (const p of parts) {
    if (cur == null) return undefined;
    cur = cur[p];
  }
  return cur;
}

function formatValue(value) {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value);
}

function unescapeSep(sep) {
  return sep.replace(/\\n/g, '\n').replace(/\\t/g, '\t');
}

function applyFilter(value, filter) {
  // Split on the FIRST colon only — arg may contain colons. Preserve
  // arg whitespace verbatim (templates may want a trailing space in the
  // join separator, e.g. "join:, ").
  const idx = filter.indexOf(':');
  const name = (idx < 0 ? filter : filter.slice(0, idx)).trim();
  const rawArg = idx < 0 ? null : filter.slice(idx + 1);
  if (name === 'join') {
    const sep = unescapeSep(rawArg == null ? ', ' : rawArg);
    if (Array.isArray(value)) return value.map(formatValue).join(sep);
    return formatValue(value);
  }
  if (name === 'default') {
    const fallback = rawArg == null ? '' : rawArg;
    if (value == null || value === '' || (Array.isArray(value) && value.length === 0)) {
      return fallback;
    }
    return formatValue(value);
  }
  return formatValue(value);
}

function render(template, data) {
  // Leading \s* is trimmed so {{ var }} works, but trailing whitespace is
  // preserved as-is — it may legitimately be part of the final filter's
  // argument (e.g. join separator "join:, ").
  return template.replace(/\{\{\s*([^}]+?)\}\}/g, (_match, expr) => {
    const segments = expr.split('|');
    const pathExpr = segments[0].trim();
    const filters = segments.slice(1);
    let value = getPath(data, pathExpr);
    if (filters.length === 0) return formatValue(value);
    for (const f of filters) value = applyFilter(value, f);
    return typeof value === 'string' ? value : formatValue(value);
  });
}

async function main() {
  const input = await readStdin();
  if (!input.template || typeof input.template !== 'string') {
    return fail('Missing required field: template');
  }
  if (!/^[a-z0-9-]+$/i.test(input.template)) {
    return fail(`Invalid template name: ${input.template} (alphanumeric + dashes only)`);
  }
  const data = input.data || {};

  const templatePath = path.join(TEMPLATE_DIR, `${input.template}.txt`);
  let template;
  try {
    template = fs.readFileSync(templatePath, 'utf-8');
  } catch (err) {
    return fail(`Template not found: ${templatePath} (${err.message})`);
  }

  const text = render(template, data).trim();
  return ok({
    template: input.template,
    text,
    char_count: text.length,
  });
}

main().catch((err) => fail(err.message || String(err)));
