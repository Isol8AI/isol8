#!/usr/bin/env node
/**
 * paperclip-http.js
 * Shared HTTP helper for Nexus's Paperclip API wrappers.
 *
 * Reads the Board API Key from PAPERCLIP_BOARD_KEY_PATH (written to the
 * shared EFS volume by the backend during provisioning). Makes authenticated
 * HTTP calls against PAPERCLIP_BASE_URL (the Paperclip sidecar at
 * localhost:3100 by default). Resolves and caches the default companyId
 * on first use so every subsequent call can scope to /api/companies/:companyId/*.
 *
 * Deterministic. Zero LLM.
 */

const fs = require('fs');
const http = require('http');
const https = require('https');
const { URL } = require('url');

const BASE_URL = process.env.PAPERCLIP_BASE_URL || 'http://localhost:3100';
const KEY_PATH = process.env.PAPERCLIP_BOARD_KEY_PATH || '/home/node/.openclaw/.paperclip/board-key';
const REQUEST_TIMEOUT_MS = 15000;

let _boardKey = null;
let _companyId = null;

function loadBoardKey() {
  if (_boardKey) return _boardKey;
  let raw;
  try {
    raw = fs.readFileSync(KEY_PATH, 'utf-8');
  } catch (err) {
    throw new Error(
      `Failed to read Paperclip board key at ${KEY_PATH}: ${err.message}. ` +
      `Is Paperclip provisioned? The backend writes this file during ` +
      `provision_paperclip_board_key after sidecar health check.`
    );
  }
  _boardKey = raw.trim();
  if (!_boardKey) throw new Error(`Board key file at ${KEY_PATH} is empty`);
  return _boardKey;
}

function pcRequest(method, path, body, query) {
  const url = new URL(path.startsWith('http') ? path : `${BASE_URL}${path}`);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
    }
  }
  const key = loadBoardKey();
  const lib = url.protocol === 'https:' ? https : http;
  const payload = body != null ? JSON.stringify(body) : null;

  return new Promise((resolve, reject) => {
    const headers = {
      'Authorization': `Bearer ${key}`,
      'Accept': 'application/json',
    };
    if (payload) {
      headers['Content-Type'] = 'application/json';
      headers['Content-Length'] = Buffer.byteLength(payload);
    }
    const req = lib.request({
      method,
      hostname: url.hostname,
      port: url.port || (url.protocol === 'https:' ? 443 : 80),
      path: url.pathname + url.search,
      headers,
      timeout: REQUEST_TIMEOUT_MS,
    }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf-8');
        let parsed = null;
        try { parsed = text ? JSON.parse(text) : null; } catch (_) { parsed = text; }
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve({ ok: true, status: res.statusCode, body: parsed });
        } else {
          const reason =
            (parsed && typeof parsed === 'object' && (parsed.error || parsed.message)) ||
            `HTTP ${res.statusCode}`;
          resolve({ ok: false, status: res.statusCode, body: parsed, reason });
        }
      });
    });
    req.on('timeout', () => req.destroy(new Error(`Paperclip request timeout (${REQUEST_TIMEOUT_MS}ms) for ${method} ${path}`)));
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

function pcGet(path, query) { return pcRequest('GET', path, null, query); }
function pcPost(path, body) { return pcRequest('POST', path, body, null); }
function pcPatch(path, body) { return pcRequest('PATCH', path, body, null); }
function pcDelete(path) { return pcRequest('DELETE', path, null, null); }

/**
 * Resolve the default company's ID. Paperclip is provisioned with a single
 * company per instance ("My Company", issuePrefix "ISL") by the backend, so
 * the first entry from /api/companies is the one Nexus scopes every write to.
 */
async function getCompanyId() {
  if (_companyId) return _companyId;
  const res = await pcGet('/api/companies');
  if (!res.ok) {
    throw new Error(`Failed to fetch /api/companies: ${res.reason}`);
  }
  const companies = Array.isArray(res.body) ? res.body : (res.body && res.body.companies) || [];
  if (companies.length === 0) {
    throw new Error(`/api/companies returned no companies — Paperclip not fully provisioned`);
  }
  _companyId = companies[0].id;
  if (!_companyId) throw new Error(`First company from /api/companies had no id field`);
  return _companyId;
}

async function readStdin() {
  if (process.stdin.isTTY) return {};
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  const text = Buffer.concat(chunks).toString('utf-8').trim();
  if (!text) return {};
  try { return JSON.parse(text); }
  catch (err) { throw new Error(`Invalid JSON on stdin: ${err.message}`); }
}

function ok(data) {
  process.stdout.write(JSON.stringify({ ok: true, ...data }) + '\n');
  process.exit(0);
}

function fail(reason, extra = {}) {
  process.stdout.write(JSON.stringify({ ok: false, reason, ...extra }) + '\n');
  process.exit(1);
}

module.exports = {
  loadBoardKey,
  getCompanyId,
  pcGet, pcPost, pcPatch, pcDelete,
  readStdin, ok, fail,
};
