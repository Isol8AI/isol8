#!/usr/bin/env node
/**
 * thread-message-sanitizer.js
 * Requirement 8: Strip all non-visible/adversarial content before AI processing.
 *
 * Deterministic. Zero LLM. Runs on EVERY incoming message from EVERY channel.
 */

function sanitize(rawContent, channel) {
  let text = rawContent || '';
  const strippedElements = [];

  // 1. Remove all HTML tags
  const htmlTagCount = (text.match(/<[^>]+>/g) || []).length;
  if (htmlTagCount > 0) {
    text = text.replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '');
    text = text.replace(/<style[^>]*>[\s\S]*?<\/style>/gi, '');
    text = text.replace(/<[^>]+>/g, ' ');
    strippedElements.push(`${htmlTagCount} HTML tags`);
  }

  // 2. Remove CSS and inline styles
  text = text.replace(/style\s*=\s*["'][^"']*["']/gi, '');

  // 3. Remove zero-width characters (used in injection attacks)
  const zeroWidthPattern = /[\u200B\u200C\u200D\u200E\u200F\uFEFF\u00AD\u034F\u2028\u2029]/g;
  const zeroWidthCount = (text.match(zeroWidthPattern) || []).length;
  if (zeroWidthCount > 0) {
    text = text.replace(zeroWidthPattern, '');
    strippedElements.push(`${zeroWidthCount} zero-width characters`);
  }

  // 4. Remove invisible text patterns (white-on-white, zero-font)
  // These survive HTML stripping as artifacts
  text = text.replace(/color\s*:\s*white/gi, '');
  text = text.replace(/font-size\s*:\s*0/gi, '');
  text = text.replace(/display\s*:\s*none/gi, '');

  // 5. Remove base64 encoded blocks (potential payloads)
  const base64Pattern = /data:[^;]+;base64,[A-Za-z0-9+/=]{50,}/g;
  const base64Count = (text.match(base64Pattern) || []).length;
  if (base64Count > 0) {
    text = text.replace(base64Pattern, '[base64 content removed]');
    strippedElements.push(`${base64Count} base64 blocks`);
  }

  // 6. Remove tracking pixels and 1x1 images
  text = text.replace(/\[image:?\s*1x1\]/gi, '');

  // 7. Decode HTML entities
  text = text.replace(/&amp;/g, '&')
             .replace(/&lt;/g, '<')
             .replace(/&gt;/g, '>')
             .replace(/&quot;/g, '"')
             .replace(/&#39;/g, "'")
             .replace(/&nbsp;/g, ' ');

  // 8. Normalize whitespace
  text = text.replace(/\s+/g, ' ').trim();

  return {
    sanitized_text: text,
    original_length: (rawContent || '').length,
    sanitized_length: text.length,
    elements_stripped: strippedElements,
    had_suspicious_content: strippedElements.length > 0,
    channel,
    timestamp: new Date().toISOString()
  };
}

async function main() {
  const input = await readStdin();
  if (!input) { process.stderr.write('No input'); process.exit(1); }

  // Handle single message or batch
  if (input.messages) {
    const results = input.messages.map(m => sanitize(m.content || m.body || m.text, m.channel));
    process.stdout.write(JSON.stringify({ sanitized: results, count: results.length }));
  } else {
    const result = sanitize(input.content || input.body || input.text, input.channel);
    process.stdout.write(JSON.stringify(result));
  }
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

module.exports = { sanitize };

if (require.main === module) { main().catch(err => { process.stderr.write(err.message); process.exit(1); }); }
