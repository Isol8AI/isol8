/**
 * Browser-compatible POSIX/USTAR tar archive utilities.
 *
 * Produces tarballs compatible with Python's `tarfile` module.
 * No external dependencies -- pure TypeScript operating on Uint8Array.
 */

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface TarEntry {
  path: string;
  content: Uint8Array;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BLOCK_SIZE = 512;
const USTAR_MAGIC = 'ustar\0'; // 6 bytes  (includes trailing NUL)
const USTAR_VERSION = '00'; // 2 bytes

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Encode a JS string to a NUL-terminated byte field of `len` bytes. */
function writeString(buf: Uint8Array, offset: number, str: string, len: number): void {
  const encoded = new TextEncoder().encode(str);
  const toCopy = Math.min(encoded.length, len - 1); // leave room for NUL
  buf.set(encoded.subarray(0, toCopy), offset);
  // Remaining bytes are already zero from initial allocation.
}

/** Write an octal number as a NUL-terminated ASCII string. */
function writeOctal(buf: Uint8Array, offset: number, value: number, len: number): void {
  // len includes the trailing NUL
  const str = value.toString(8).padStart(len - 1, '0');
  writeString(buf, offset, str, len);
}

/** Read a NUL-terminated ASCII string from a byte buffer. */
function readString(buf: Uint8Array, offset: number, len: number): string {
  let end = offset;
  const limit = offset + len;
  while (end < limit && buf[end] !== 0) {
    end++;
  }
  return new TextDecoder().decode(buf.subarray(offset, end));
}

/** Parse an octal ASCII field to a number. */
function readOctal(buf: Uint8Array, offset: number, len: number): number {
  const s = readString(buf, offset, len).trim();
  return s.length === 0 ? 0 : parseInt(s, 8);
}

/** Check whether an entire 512-byte block is all zeros. */
function isZeroBlock(buf: Uint8Array, offset: number): boolean {
  for (let i = 0; i < BLOCK_SIZE; i++) {
    if (buf[offset + i] !== 0) return false;
  }
  return true;
}

/** Strip leading `./` or `/` from a path. */
function cleanPath(p: string): string {
  let s = p;
  while (s.startsWith('./')) s = s.slice(2);
  while (s.startsWith('/')) s = s.slice(1);
  return s;
}

/**
 * Compute the USTAR header checksum.
 * Per spec: sum of all 512 bytes treating the 8-byte checksum field
 * (offsets 148--155) as ASCII spaces (0x20).
 */
function computeChecksum(header: Uint8Array): number {
  let sum = 0;
  for (let i = 0; i < BLOCK_SIZE; i++) {
    if (i >= 148 && i < 156) {
      sum += 0x20; // treat checksum field as spaces
    } else {
      sum += header[i];
    }
  }
  return sum;
}

// ---------------------------------------------------------------------------
// createTar
// ---------------------------------------------------------------------------

/**
 * Create a USTAR tar archive from an array of file entries.
 *
 * The returned `Uint8Array` is always a multiple of 512 bytes and ends with
 * two zero blocks as required by the POSIX spec.
 */
export function createTar(entries: TarEntry[]): Uint8Array {
  // Pre-calculate total size so we can allocate once.
  let totalSize = 0;
  for (const entry of entries) {
    totalSize += BLOCK_SIZE; // header
    totalSize += Math.ceil(entry.content.length / BLOCK_SIZE) * BLOCK_SIZE; // padded content
  }
  totalSize += BLOCK_SIZE * 2; // end-of-archive marker (two zero blocks)

  const out = new Uint8Array(totalSize); // pre-zeroed
  let offset = 0;

  for (const entry of entries) {
    const header = out.subarray(offset, offset + BLOCK_SIZE);

    // -- USTAR header layout --
    // name       0   100
    // mode     100     8
    // uid      108     8
    // gid      116     8
    // size     124    12
    // mtime    136    12
    // chksum   148     8
    // typeflag 156     1
    // linkname 157   100
    // magic    257     6
    // version  263     2
    // uname    265    32
    // gname    297    32
    // devmajor 329     8
    // devminor 337     8
    // prefix   345   155

    const path = entry.path;

    // If path > 100 chars, split into prefix (155) + name (100).
    if (path.length <= 100) {
      writeString(header, 0, path, 100);
    } else {
      // Find a `/` to split on.  prefix gets the directory portion.
      const splitAt = path.lastIndexOf('/', 155);
      if (splitAt === -1 || splitAt === 0) {
        // Can't split cleanly -- just truncate (shouldn't happen with sane paths).
        writeString(header, 0, path.slice(0, 100), 100);
      } else {
        const prefix = path.slice(0, splitAt);
        const name = path.slice(splitAt + 1);
        writeString(header, 0, name, 100);
        writeString(header, 345, prefix, 155);
      }
    }

    writeOctal(header, 100, 0o644, 8); // mode
    writeOctal(header, 108, 0, 8); // uid
    writeOctal(header, 116, 0, 8); // gid
    writeOctal(header, 124, entry.content.length, 12); // size
    writeOctal(header, 136, 0, 12); // mtime (epoch 0 is fine)
    // chksum placeholder -- filled after computation
    header[156] = 0x30; // typeflag '0' (regular file)
    // linkname stays zero

    // USTAR magic + version
    const magicBytes = new TextEncoder().encode(USTAR_MAGIC);
    header.set(magicBytes, 257);
    const versionBytes = new TextEncoder().encode(USTAR_VERSION);
    header.set(versionBytes, 263);

    // uname / gname (optional, leave empty -- zeros are fine)

    // Compute and write checksum.
    const checksum = computeChecksum(header);
    // Checksum is written as 6 octal digits + NUL + space.
    const chksumStr = checksum.toString(8).padStart(6, '0');
    writeString(header, 148, chksumStr, 7);
    header[155] = 0x20; // trailing space

    offset += BLOCK_SIZE;

    // Write content.
    if (entry.content.length > 0) {
      out.set(entry.content, offset);
      offset += Math.ceil(entry.content.length / BLOCK_SIZE) * BLOCK_SIZE;
    }
  }

  // Two zero blocks are already present because the buffer was pre-zeroed.
  // Just advance offset past them for completeness.
  offset += BLOCK_SIZE * 2;

  return out;
}

// ---------------------------------------------------------------------------
// extractTar
// ---------------------------------------------------------------------------

/**
 * Extract regular files from a USTAR/POSIX tar archive.
 *
 * Directory entries and other special types are silently skipped.
 * Paths are cleaned (leading `./` and `/` stripped).
 */
export function extractTar(tar: Uint8Array): TarEntry[] {
  const entries: TarEntry[] = [];
  let offset = 0;
  let consecutiveZeroBlocks = 0;

  while (offset + BLOCK_SIZE <= tar.length) {
    // Detect end-of-archive (two consecutive zero blocks).
    if (isZeroBlock(tar, offset)) {
      consecutiveZeroBlocks++;
      if (consecutiveZeroBlocks >= 2) break;
      offset += BLOCK_SIZE;
      continue;
    }
    consecutiveZeroBlocks = 0;

    const header = tar.subarray(offset, offset + BLOCK_SIZE);

    // Read name + optional prefix for USTAR.
    let name = readString(header, 0, 100);
    const magic = readString(header, 257, 6);

    if (magic === 'ustar' || magic === 'ustar\0') {
      const prefix = readString(header, 345, 155);
      if (prefix.length > 0) {
        name = prefix + '/' + name;
      }
    }

    const size = readOctal(header, 124, 12);
    const typeflag = header[156];

    offset += BLOCK_SIZE; // advance past header

    // Only extract regular files (typeflag '0' or NUL).
    const isRegularFile = typeflag === 0x30 /* '0' */ || typeflag === 0x00 /* NUL */;

    if (isRegularFile && name.length > 0) {
      const content = tar.slice(offset, offset + size);
      entries.push({
        path: cleanPath(name),
        content,
      });
    }

    // Advance past content blocks (padded to 512 boundary).
    if (size > 0) {
      offset += Math.ceil(size / BLOCK_SIZE) * BLOCK_SIZE;
    }
  }

  return entries;
}
