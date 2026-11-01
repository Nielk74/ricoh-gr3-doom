// GPL-2.0-only. Public synthetic codec oracles from Ricoh-GRMod; no firmware.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync} from 'node:fs';
import {registerHooks} from 'node:module';

registerHooks({resolve(specifier, context, next) {
  try { return next(specifier, context); }
  catch (error) {
    if (specifier.startsWith('.') && !/\.[a-z]+$/i.test(specifier)) {
      return next(specifier + '.ts', context);
    }
    throw error;
  }
}});
const {Firmware, FirmwareError, HDR, MAGIC, sum32, parseFrames, wrapStream,
       build, buildGrown, verifyContainer, FRAME_SIZE} = await import('../vendor/grmod/container.ts');

test('150 synthetic parser oracles, with four output-length hints each', () => {
  const cases = JSON.parse(readFileSync(new URL('fixtures/parse-fuzz.json', import.meta.url), 'utf8'));
  assert.equal(cases.length, 150);
  for (const [i, c] of cases.entries()) {
    for (const hint of [undefined, 1, c.decoded ? c.decoded.length / 2 : 10, 100000]) {
      const raw = Buffer.from(c.src, 'hex');
      if (!c.ok) {
        assert.throws(() => parseFrames(raw, hint), e => e instanceof FirmwareError && e.code === 'bad-stream', `case ${i}`);
      } else {
        const got = parseFrames(raw, hint);
        assert.equal(Buffer.from(got.decoded).toString('hex'), c.decoded, `case ${i}`);
        assert.equal(got.streamEnd, c.streamEnd, `case ${i}`);
        assert.deepEqual(got.frames.map(f => [f.start, f.end, f.stored, f.outStart, f.outLen, f.crossref]), c.frames, `case ${i}`);
      }
    }
  }
});

function synthetic(length = 64) {
  const header = new Uint8Array(HDR), h = new DataView(header.buffer);
  h.setUint32(0x30, 588, true);
  h.setUint32(0x78, 588 | (588 << 16), true); h.setUint32(0x7c, MAGIC, true);
  const payload = new Uint8Array(length), stream = new Uint8Array(length + 4);
  stream.set([(0x8000 | length) >>> 8, length & 255]); stream.set(payload, 2);
  return new Firmware(wrapStream({header, models: new Uint8Array(), project: 588, fType: 0}, stream, payload.length));
}

test('word sums include unaligned input, trailing bytes and overflow', () => {
  const raw = Uint8Array.from([99, 255, 255, 255, 255, 2, 0, 0, 0, 3]);
  assert.equal(sum32(raw.subarray(1, 9)), 1);
  assert.equal(sum32(raw.subarray(1)), 4);
  assert.equal(sum32(Uint8Array.of(1, 2, 3)), 0x030201);
});

test('valid container roundtrip and checksum-preserving edit', () => {
  const fw = synthetic();
  assert.deepEqual(build(fw, fw.decoded).out, fw.raw);
  const edited = fw.decoded.slice(), words = new DataView(edited.buffer);
  words.setUint32(0, 123, true); words.setUint32(60, -123 >>> 0, true);
  const built = build(fw, edited);
  assert.deepEqual(built.reencoded, [0]);
  assert.deepEqual(new Firmware(built.out).decoded, edited);
  assert.ok(Object.values(verifyContainer(built.out, edited).checks).every(Boolean));
  assert.deepEqual(built.out.subarray(0, HDR), fw.header);
});

test('corrupt file checksums and mismatched payload sums are rejected', () => {
  const fw = synthetic(), corrupt = fw.raw.slice(); corrupt[0] ^= 1;
  assert.throws(() => new Firmware(corrupt), e => e.code === 'bad-checksum');
  const edited = fw.decoded.slice(); edited[0] = 1;
  assert.throws(() => build(fw, edited), e => e.code === 'payload-sum-nonzero');
});

test('growth inserts complete frames and preserves existing decoded bytes', () => {
  const fw = synthetic(FRAME_SIZE), grown = new Uint8Array(fw.decoded.length + FRAME_SIZE);
  const result = buildGrown(fw, grown, [{at: 32, length: FRAME_SIZE}]);
  assert.deepEqual(new Firmware(result.out).decoded, grown);
  assert.ok(Object.values(verifyContainer(result.out, grown).checks).every(Boolean));
});
