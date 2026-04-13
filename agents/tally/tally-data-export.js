#!/usr/bin/env node
/**
 * tally-data-export.js
 * Requirements 4, 57: All data exportable in standard formats. No proprietary lock-in.
 *
 * Deterministic formatting. Zero LLM.
 */

function formatForExport(data, format) {
  if (format === 'json') {
    return JSON.stringify(data, null, 2);
  }

  if (format === 'csv') {
    if (!Array.isArray(data) || data.length === 0) return '';
    const headers = Object.keys(data[0]);
    const rows = data.map(row =>
      headers.map(h => {
        const val = row[h];
        if (val === null || val === undefined) return '';
        if (typeof val === 'object') return JSON.stringify(val).replace(/"/g, '""');
        return String(val).includes(',') ? `"${val}"` : val;
      }).join(',')
    );
    return [headers.join(','), ...rows].join('\n');
  }

  return JSON.stringify(data);
}

async function main() {
  const input = await readStdin();
  if (!input) {
    process.stderr.write('No input provided');
    process.exit(1);
  }

  const exportType = input.export_type || 'full';
  const format = input.format || 'json';
  const exports = {};

  if (exportType === 'full' || exportType === 'transactions') {
    exports.transactions = {
      data: input.transactions || [],
      format,
      filename: `tally-transactions-${new Date().toISOString().split('T')[0]}.${format}`
    };
  }

  if (exportType === 'full' || exportType === 'audit') {
    exports.audit_trail = {
      data: input.audit_entries || [],
      format: 'json',
      filename: `tally-audit-trail-${new Date().toISOString().split('T')[0]}.json`
    };
  }

  if (exportType === 'full' || exportType === 'approvals') {
    exports.approval_history = {
      data: input.approvals || [],
      format,
      filename: `tally-approvals-${new Date().toISOString().split('T')[0]}.${format}`
    };
  }

  if (exportType === 'full' || exportType === 'metrics') {
    exports.metrics_history = {
      data: input.metrics || [],
      format,
      filename: `tally-metrics-${new Date().toISOString().split('T')[0]}.${format}`
    };
  }

  if (exportType === 'full' || exportType === 'tax') {
    exports.tax_data = {
      data: input.tax_data || [],
      format,
      filename: `tally-tax-prep-${new Date().toISOString().split('T')[0]}.${format}`
    };
  }

  // Format each export
  for (const [key, exp] of Object.entries(exports)) {
    exp.formatted = formatForExport(exp.data, exp.format);
    exp.size_bytes = Buffer.byteLength(exp.formatted, 'utf8');
  }

  const result = {
    exports,
    total_files: Object.keys(exports).length,
    export_type: exportType,
    format,
    timestamp: new Date().toISOString()
  };

  process.stdout.write(JSON.stringify(result));
}

function readStdin() {
  return new Promise((resolve) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => data += chunk);
    process.stdin.on('end', () => {
      try { resolve(JSON.parse(data)); }
      catch { resolve(null); }
    });
    if (process.stdin.isTTY) resolve(null);
  });
}

if (require.main === module) {
  main().catch(err => {
    process.stderr.write(err.message);
    process.exit(1);
  });
}
