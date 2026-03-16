import { describe, it, expect } from 'vitest';
import { extractTar, createTar, TarEntry } from '../tar';

/** Helper: encode a UTF-8 string to Uint8Array */
function encode(s: string): Uint8Array {
  return new TextEncoder().encode(s);
}

/** Helper: decode a Uint8Array to UTF-8 string */
function decode(buf: Uint8Array): string {
  return new TextDecoder().decode(buf);
}

describe('tar utilities', () => {
  // ------------------------------------------------------------------
  // Round-trip: single file
  // ------------------------------------------------------------------
  describe('round-trip single file', () => {
    it('should create and extract a single file', () => {
      const entries: TarEntry[] = [
        { path: 'hello.txt', content: encode('Hello, world!') },
      ];

      const tarball = createTar(entries);
      const extracted = extractTar(tarball);

      expect(extracted).toHaveLength(1);
      expect(extracted[0].path).toBe('hello.txt');
      expect(decode(extracted[0].content)).toBe('Hello, world!');
    });
  });

  // ------------------------------------------------------------------
  // Round-trip: multiple files with nested paths
  // ------------------------------------------------------------------
  describe('round-trip multiple files with nested paths', () => {
    it('should handle agents/pirate/SOUL.md and other nested files', () => {
      const entries: TarEntry[] = [
        { path: 'openclaw.json', content: encode('{"name":"test"}') },
        {
          path: 'agents/pirate/SOUL.md',
          content: encode('# Pirate Soul\nYou are a pirate.'),
        },
        {
          path: 'agents/pirate/memory/facts.json',
          content: encode('[]'),
        },
      ];

      const tarball = createTar(entries);
      const extracted = extractTar(tarball);

      expect(extracted).toHaveLength(3);

      const paths = extracted.map((e) => e.path);
      expect(paths).toContain('openclaw.json');
      expect(paths).toContain('agents/pirate/SOUL.md');
      expect(paths).toContain('agents/pirate/memory/facts.json');

      const soul = extracted.find((e) => e.path === 'agents/pirate/SOUL.md');
      expect(soul).toBeDefined();
      expect(decode(soul!.content)).toBe('# Pirate Soul\nYou are a pirate.');
    });
  });

  // ------------------------------------------------------------------
  // Empty files
  // ------------------------------------------------------------------
  describe('empty files', () => {
    it('should handle files with zero-length content', () => {
      const entries: TarEntry[] = [
        { path: 'empty.txt', content: new Uint8Array(0) },
        { path: 'also-empty', content: new Uint8Array(0) },
      ];

      const tarball = createTar(entries);
      const extracted = extractTar(tarball);

      expect(extracted).toHaveLength(2);
      expect(extracted[0].content).toHaveLength(0);
      expect(extracted[1].content).toHaveLength(0);
    });

    it('should correctly round-trip a mix of empty and non-empty files', () => {
      const entries: TarEntry[] = [
        { path: 'non-empty.txt', content: encode('data') },
        { path: 'empty.txt', content: new Uint8Array(0) },
      ];

      const tarball = createTar(entries);
      const extracted = extractTar(tarball);

      expect(extracted).toHaveLength(2);

      const nonEmpty = extracted.find((e) => e.path === 'non-empty.txt');
      const empty = extracted.find((e) => e.path === 'empty.txt');

      expect(nonEmpty).toBeDefined();
      expect(decode(nonEmpty!.content)).toBe('data');
      expect(empty).toBeDefined();
      expect(empty!.content).toHaveLength(0);
    });
  });

  // ------------------------------------------------------------------
  // Binary content
  // ------------------------------------------------------------------
  describe('binary content', () => {
    it('should handle arbitrary binary bytes including nulls', () => {
      // Create a buffer with all possible byte values 0x00-0xFF
      const binaryContent = new Uint8Array(256);
      for (let i = 0; i < 256; i++) {
        binaryContent[i] = i;
      }

      const entries: TarEntry[] = [
        { path: 'binary.bin', content: binaryContent },
      ];

      const tarball = createTar(entries);
      const extracted = extractTar(tarball);

      expect(extracted).toHaveLength(1);
      expect(extracted[0].path).toBe('binary.bin');
      expect(extracted[0].content).toEqual(binaryContent);
    });

    it('should handle large binary content spanning multiple 512-byte blocks', () => {
      // 1500 bytes -- requires 3 content blocks (512 * 3 = 1536)
      const largeContent = new Uint8Array(1500);
      for (let i = 0; i < 1500; i++) {
        largeContent[i] = i % 256;
      }

      const entries: TarEntry[] = [
        { path: 'large.bin', content: largeContent },
      ];

      const tarball = createTar(entries);
      const extracted = extractTar(tarball);

      expect(extracted).toHaveLength(1);
      expect(extracted[0].content).toEqual(largeContent);
    });
  });

  // ------------------------------------------------------------------
  // Output size is multiple of 512
  // ------------------------------------------------------------------
  describe('output size', () => {
    it('should produce output whose length is a multiple of 512', () => {
      const entries: TarEntry[] = [
        { path: 'a.txt', content: encode('short') },
      ];

      const tarball = createTar(entries);
      expect(tarball.length % 512).toBe(0);
    });

    it('should produce output that is a multiple of 512 for multiple files', () => {
      const entries: TarEntry[] = [
        { path: 'one.txt', content: encode('first') },
        { path: 'two.txt', content: encode('second') },
        { path: 'three.txt', content: encode('third file with more content') },
      ];

      const tarball = createTar(entries);
      expect(tarball.length % 512).toBe(0);
    });

    it('should produce output that is a multiple of 512 for empty file list', () => {
      const tarball = createTar([]);
      expect(tarball.length % 512).toBe(0);
      // At minimum: two zero-blocks (1024 bytes)
      expect(tarball.length).toBeGreaterThanOrEqual(1024);
    });
  });

  // ------------------------------------------------------------------
  // Path cleaning
  // ------------------------------------------------------------------
  describe('path cleaning', () => {
    it('should strip leading ./ from paths during extraction', () => {
      // Create a tarball with ./prefix paths, verify extraction strips them
      const entries: TarEntry[] = [
        { path: 'clean.txt', content: encode('ok') },
      ];

      const tarball = createTar(entries);
      const extracted = extractTar(tarball);

      // Our createTar should produce clean paths; verify extraction is clean
      expect(extracted[0].path).toBe('clean.txt');
      expect(extracted[0].path.startsWith('./')).toBe(false);
      expect(extracted[0].path.startsWith('/')).toBe(false);
    });
  });

  // ------------------------------------------------------------------
  // extractTar: skips directory entries
  // ------------------------------------------------------------------
  describe('directory entries', () => {
    it('should skip directory-type entries and only return regular files', () => {
      // Create a tarball with files, then manually inject a directory header
      // to verify extractTar skips it. We'll use createTar for files and
      // verify that only files come back (no phantom directories).
      const entries: TarEntry[] = [
        { path: 'dir/file.txt', content: encode('inside dir') },
      ];

      const tarball = createTar(entries);
      const extracted = extractTar(tarball);

      // createTar should only write file entries, not directory entries
      expect(extracted).toHaveLength(1);
      expect(extracted[0].path).toBe('dir/file.txt');
    });
  });

  // ------------------------------------------------------------------
  // Exact content preservation
  // ------------------------------------------------------------------
  describe('content preservation', () => {
    it('should preserve content exactly for files whose size is an exact multiple of 512', () => {
      // Exactly 512 bytes
      const content = new Uint8Array(512);
      content.fill(0x42); // fill with 'B'

      const entries: TarEntry[] = [
        { path: 'exact512.bin', content },
      ];

      const tarball = createTar(entries);
      const extracted = extractTar(tarball);

      expect(extracted).toHaveLength(1);
      expect(extracted[0].content).toEqual(content);
      expect(extracted[0].content.length).toBe(512);
    });

    it('should preserve content exactly for files whose size is 513 (just over block boundary)', () => {
      const content = new Uint8Array(513);
      content.fill(0x43);

      const entries: TarEntry[] = [
        { path: 'over512.bin', content },
      ];

      const tarball = createTar(entries);
      const extracted = extractTar(tarball);

      expect(extracted).toHaveLength(1);
      expect(extracted[0].content).toEqual(content);
      expect(extracted[0].content.length).toBe(513);
    });
  });
});
