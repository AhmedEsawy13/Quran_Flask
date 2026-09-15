/**
 * Dependency-free QVP1 decoder and Canvas2D renderer.
 *
 * Vendored from https://github.com/quran-ws/quran-engine (MIT) web/lite.mjs
 * at v0.1.1. Keep decoder behaviour identical to upstream.
 */

const limits = {
  fileBytes: 2 * 1024 * 1024,
  paths: 20000,
  operations: 500000,
  coordinates: 2000000,
  decodedBytes: 16 * 1024 * 1024,
  records: 4096,
};

export type QvpWord = {
  idx: number;
  surah: number;
  ayah: number;
  word: number;
  lineIdx: number;
  ayahIdx: number;
  firstPath: number;
  nPaths: number;
  box: [number, number, number, number];
  /** Letter + tashkeel box, excluding pause signs. */
  inkBox: [number, number, number, number];
  /** Printed pause-sign box, or null when this word has no مجمع وقف. */
  pauseBox: [number, number, number, number] | null;
};

export type QvpView = {
  scale: number;
  x: number;
  y: number;
};

/** `Family::Waqf` in qvp-format. Pause signs attached to a word. */
export const QVP_FAMILY_WAQF = 4;
/** `Mark::Saktah` — pause, but classified as a reading sign, not Family::Waqf. */
export const QVP_MARK_SAKTAH = 26;

export function isQvpPausePath(family: number, mark: number) {
  return family === QVP_FAMILY_WAQF || mark === QVP_MARK_SAKTAH;
}

type QvpPath = {
  ops: Uint8Array;
  pts: Float32Array;
  box: [number, number, number, number];
  rule: CanvasFillRule;
  family: number;
  mark: number;
};

type QvpGeometry = {
  width: number;
  height: number;
  number: number;
  paths: QvpPath[];
  words: QvpWord[];
};

type DrawOptions = {
  scale?: number;
  x?: number;
  y?: number;
  ink?: string;
  hideWaqf?: boolean;
};

function asBytes(buffer: ArrayBuffer | ArrayBufferView) {
  return buffer instanceof ArrayBuffer
    ? new Uint8Array(buffer)
    : new Uint8Array(buffer.buffer, buffer.byteOffset, buffer.byteLength);
}

export async function loadPage(url: string, options?: RequestInit) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`Could not load QVP page: HTTP ${response.status}`);
  return decodePage(await response.arrayBuffer());
}

export function decodePage(buffer: ArrayBuffer | ArrayBufferView) {
  return new QvpLitePage(decodeGeometry(buffer));
}

export function decodeGeometry(buffer: ArrayBuffer | ArrayBufferView): QvpGeometry {
  const bytes = asBytes(buffer);
  if (bytes.byteLength < 64) throw new Error("Truncated QVP header");
  if (bytes.byteLength > limits.fileBytes) throw new Error("QVP page is too large");
  const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const u16 = (offset: number) => data.getUint16(offset, true);
  const u32 = (offset: number) => data.getUint32(offset, true);
  const f32 = (offset: number) => data.getFloat32(offset, true);
  if (u32(0) !== 0x31505651 || u16(4) !== 1) throw new Error("Expected a QVP1 page");

  const quant = u16(6);
  const number = u16(8);
  const width = f32(12);
  const height = f32(16);
  const nLines = u16(20);
  const nAyahs = u16(22);
  const nWords = u16(24);
  const nDecos = u16(26);
  const nPaths = u32(28);
  const nStrings = u16(32);
  const nGlyphs = u16(34);
  const nInstances = u16(36);
  if (
    nPaths > limits.paths || nLines > limits.records || nAyahs > limits.records
    || nWords > limits.records || nDecos > limits.records || nStrings > limits.records
    || nGlyphs > limits.records || nInstances > limits.records
  ) {
    throw new Error("QVP page exceeds decoder limits");
  }
  if (!quant || !Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    throw new Error("Invalid QVP dimensions");
  }

  let sectionOffset = 64;
  const sections = Array.from({length: 6}, (_, i) => {
    const start = sectionOffset;
    sectionOffset += u32(40 + i * 4);
    if (sectionOffset > bytes.length) throw new Error("Invalid QVP section length");
    return {start, end: sectionOffset};
  });
  if (sectionOffset !== bytes.length) throw new Error("Invalid QVP length");

  const reader = (section: {start: number; end: number}) => ({
    position: section.start,
    byte() {
      if (this.position >= section.end) throw new Error("Truncated QVP section");
      return bytes[this.position++];
    },
    varint() {
      let value = 0;
      for (let shift = 0; shift < 35; shift += 7) {
        const next = this.byte();
        if (shift === 28 && next > 15) throw new Error("Invalid QVP varint");
        value += (next & 127) * 2 ** shift;
        if (next < 128) return value;
      }
      throw new Error("Invalid QVP varint");
    },
    zigzag() {
      const value = this.varint();
      return (value >>> 1) ^ -(value & 1);
    },
    float() {
      if (this.position + 4 > section.end) throw new Error("Truncated QVP float");
      const value = f32(this.position);
      this.position += 4;
      return value;
    },
  });

  const metadataSize = sections[0].end - sections[0].start;
  const minimumMetadataSize = nLines * 2 + nAyahs * 8 + nWords * 12
    + nPaths * 5 + nDecos * 7 + nGlyphs * 5 + nInstances * 26;
  if (minimumMetadataSize > metadataSize) throw new Error("Invalid QVP metadata counts");

  const metadata = reader(sections[0]);
  for (let i = 0; i < nLines; i++) {
    metadata.byte();
    metadata.varint();
  }
  for (let i = 0; i < nAyahs; i++) {
    metadata.zigzag();
    metadata.zigzag();
    metadata.byte();
    metadata.byte();
    metadata.byte();
    metadata.varint();
    metadata.varint();
    metadata.varint();
  }
  let surah = 0;
  let ayah = 0;
  let word = 0;
  let lineIdx = 0;
  let ayahIdx = 0;
  const wordRecords = Array.from({length: nWords}, (_, idx) => {
    const firstPathDelta = metadata.zigzag();
    surah += metadata.zigzag();
    ayah += metadata.zigzag();
    word += metadata.zigzag();
    lineIdx += metadata.zigzag();
    ayahIdx += metadata.zigzag();
    for (let i = 0; i < 5; i++) metadata.varint();
    return {
      idx,
      surah,
      ayah,
      word,
      lineIdx,
      ayahIdx,
      firstPathDelta,
      nPaths: metadata.varint(),
    };
  });
  const columns = Array.from({length: 4}, () =>
    Uint8Array.from({length: nPaths}, () => metadata.byte()));
  const counts = Uint32Array.from({length: nPaths}, () => metadata.varint());
  const nInstancePaths = columns[3].reduce((sum, flags) => sum + Number(Boolean(flags & 16)), 0);
  const instanceBoxes = Array.from({length: nInstancePaths}, () => {
    const x0 = metadata.zigzag();
    const y0 = metadata.zigzag();
    const x1 = x0 + metadata.zigzag();
    const y1 = y0 + metadata.zigzag();
    return [
      Math.fround(x0 / quant),
      Math.fround(y0 / quant),
      Math.fround(x1 / quant),
      Math.fround(y1 / quant),
    ] as [number, number, number, number];
  });
  for (let i = 0; i < nDecos; i++) {
    metadata.zigzag();
    metadata.byte();
    metadata.zigzag();
    for (let j = 0; j < 4; j++) metadata.varint();
  }
  const glyphCounts = Array.from({length: nGlyphs}, () => {
    const count = metadata.varint();
    for (let i = 0; i < 4; i++) metadata.zigzag();
    return count;
  });
  const instances = Array.from({length: nInstances}, () => {
    const instance = [
      metadata.byte() | metadata.byte() << 8,
      ...Array.from({length: 6}, () => metadata.float()),
    ];
    if (instance.some((value) => !Number.isFinite(value))) throw new Error("Invalid QVP transform");
    return instance;
  });
  if (metadata.position !== sections[0].end) throw new Error("Invalid QVP metadata");

  const wireCounts = [...counts.filter((_, i) => !(columns[3][i] & 16)), ...glyphCounts];
  const wireOperations = wireCounts.reduce((sum, count) => sum + count, 0);
  if (
    !Number.isSafeInteger(wireOperations) || wireOperations > limits.operations
    || Math.ceil(wireOperations / 4) !== sections[1].end - sections[1].start
  ) {
    throw new Error("Invalid QVP operation count");
  }

  const closeReader = reader(sections[2]);
  let closePosition = 0;
  const nCloses = closeReader.varint();
  if (
    nCloses > sections[2].end - closeReader.position
    || wireOperations + nCloses > limits.operations
  ) throw new Error("Invalid QVP close count");
  const closePositions = Array.from({length: nCloses}, () =>
    closePosition += closeReader.varint());
  if (closeReader.position !== sections[2].end) throw new Error("Invalid QVP close paths");

  const xReader = reader(sections[3]);
  const yReader = reader(sections[4]);
  let previousX = 0;
  let previousY = 0;
  let operationIndex = 0;
  let closeIndex = 0;
  const shapes = wireCounts.map((count) => {
    const ops: number[] = [];
    const pts: number[] = [];
    for (let i = 0; i < count; i++) {
      const operation = bytes[sections[1].start + (operationIndex >> 2)] >> ((operationIndex % 4) * 2) & 3;
      ops.push(operation);
      for (let p = 0; p < [1, 1, 2, 3][operation]; p++) {
        previousX += xReader.zigzag();
        previousY += yReader.zigzag();
        pts.push(previousX, previousY);
      }
      operationIndex += 1;
      while (closePositions[closeIndex] === operationIndex) {
        ops.push(4);
        closeIndex += 1;
      }
    }
    if (ops[0] === 0) {
      previousX = pts[0];
      previousY = pts[1];
    }
    return {ops, pts};
  });
  if (
    Math.ceil(operationIndex / 4) !== sections[1].end - sections[1].start
    || closeIndex !== closePositions.length
    || xReader.position !== sections[3].end || yReader.position !== sections[4].end
  ) {
    throw new Error("Invalid QVP geometry");
  }

  const strings = reader(sections[5]);
  for (let i = 0; i < nStrings; i++) {
    const length = strings.varint();
    strings.position += length;
    if (strings.position > sections[5].end) throw new Error("Truncated QVP string");
  }
  if (strings.position !== sections[5].end) throw new Error("Invalid QVP strings");

  let directShape = 0;
  let instanceBox = 0;
  let decodedSize = nPaths * 32;
  let decodedOperations = 0;
  let decodedCoordinates = 0;
  const paths = Array.from(counts, (reference, i): QvpPath => {
    const isInstance = Boolean(columns[3][i] & 16);
    const transform = isInstance ? instances[reference] : null;
    if (isInstance && (!transform || transform[0] >= nGlyphs)) throw new Error("Invalid QVP glyph instance");
    const shape = isInstance && transform
      ? shapes[shapes.length - nGlyphs + transform[0]]
      : shapes[directShape++];
    if (!shape) throw new Error("Invalid QVP path shape");
    decodedOperations += shape.ops.length;
    decodedCoordinates += shape.pts.length;
    decodedSize += shape.ops.length + shape.pts.length * 4;
    if (
      !Number.isSafeInteger(decodedSize) || decodedOperations > limits.operations
      || decodedCoordinates > limits.coordinates || decodedSize > limits.decodedBytes
      || decodedSize > bytes.length * 64
    ) {
      throw new Error("QVP decoded geometry is too large");
    }

    const pts = new Float32Array(shape.pts.length);
    const box: [number, number, number, number] = isInstance
      ? instanceBoxes[instanceBox++]
      : [Infinity, Infinity, -Infinity, -Infinity];
    for (let p = 0; p < pts.length; p += 2) {
      const x = shape.pts[p] / quant;
      const y = shape.pts[p + 1] / quant;
      let outputX = x;
      let outputY = y;
      if (isInstance && transform) {
        const [, a, b, c, d, e, f] = transform;
        outputX = a * x + c * y + e;
        outputY = b * x + d * y + f;
      }
      if (!Number.isFinite(outputX) || !Number.isFinite(outputY)) throw new Error("Invalid QVP coordinate");
      pts[p] = outputX;
      pts[p + 1] = outputY;
      if (!isInstance) {
        box[0] = Math.min(box[0], pts[p]);
        box[1] = Math.min(box[1], pts[p + 1]);
        box[2] = Math.max(box[2], pts[p]);
        box[3] = Math.max(box[3], pts[p + 1]);
      }
    }
    if (!box || box.some((value) => !Number.isFinite(value))) throw new Error("Invalid QVP path box");
    return {
      ops: Uint8Array.from(shape.ops),
      pts,
      box,
      rule: columns[3][i] & 1 ? "evenodd" : "nonzero",
      family: columns[2][i],
      mark: columns[1][i],
    };
  });

  let previousWordEnd = 0;
  const words = wordRecords.map((record): QvpWord => {
    const {firstPathDelta, nPaths: wordPathCount} = record;
    const firstPath = previousWordEnd + firstPathDelta;
    const endPath = firstPath + wordPathCount;
    if (firstPath < 0 || endPath > nPaths) throw new Error("Invalid QVP word path range");
    const box: [number, number, number, number] = [Infinity, Infinity, -Infinity, -Infinity];
    const inkBox: [number, number, number, number] = [Infinity, Infinity, -Infinity, -Infinity];
    const pauseBox: [number, number, number, number] = [Infinity, Infinity, -Infinity, -Infinity];
    let hasPause = false;
    for (let path = firstPath; path < endPath; path++) {
      const pathBox = paths[path].box;
      box[0] = Math.min(box[0], pathBox[0]);
      box[1] = Math.min(box[1], pathBox[1]);
      box[2] = Math.max(box[2], pathBox[2]);
      box[3] = Math.max(box[3], pathBox[3]);
      if (isQvpPausePath(paths[path].family, paths[path].mark)) {
        hasPause = true;
        pauseBox[0] = Math.min(pauseBox[0], pathBox[0]);
        pauseBox[1] = Math.min(pauseBox[1], pathBox[1]);
        pauseBox[2] = Math.max(pauseBox[2], pathBox[2]);
        pauseBox[3] = Math.max(pauseBox[3], pathBox[3]);
        continue;
      }
      inkBox[0] = Math.min(inkBox[0], pathBox[0]);
      inkBox[1] = Math.min(inkBox[1], pathBox[1]);
      inkBox[2] = Math.max(inkBox[2], pathBox[2]);
      inkBox[3] = Math.max(inkBox[3], pathBox[3]);
    }
    previousWordEnd = endPath;
    if (box.some((value) => !Number.isFinite(value))) throw new Error("Invalid QVP word box");
    const overlayBox = inkBox.some((value) => !Number.isFinite(value)) ? box : inkBox;
    return {
      idx: record.idx,
      surah: record.surah,
      ayah: record.ayah,
      word: record.word,
      lineIdx: record.lineIdx,
      ayahIdx: record.ayahIdx,
      firstPath,
      nPaths: wordPathCount,
      box,
      inkBox: overlayBox,
      pauseBox: hasPause && !pauseBox.some((value) => !Number.isFinite(value)) ? pauseBox : null,
    };
  });
  return {width, height, number, paths, words};
}

export class QvpLitePage {
  width: number;
  height: number;
  number: number;
  words: QvpWord[];
  pauseSize: {width: number; height: number};
  #paths: Array<{path: Path2D; rule: CanvasFillRule; family: number; mark: number}>;
  #decorationPaths: number[];

  constructor({width, height, number, paths, words}: QvpGeometry) {
    this.width = width;
    this.height = height;
    this.number = number;
    this.words = words;
    const pauseWidths = words.flatMap((word) => word.pauseBox ? [word.pauseBox[2] - word.pauseBox[0]] : []);
    const pauseHeights = words.flatMap((word) => word.pauseBox ? [word.pauseBox[3] - word.pauseBox[1]] : []);
    pauseWidths.sort((a, b) => a - b);
    pauseHeights.sort((a, b) => a - b);
    this.pauseSize = {
      width: pauseWidths[Math.floor(pauseWidths.length / 2)] || 2.4,
      height: pauseHeights[Math.floor(pauseHeights.length / 2)] || 2.8,
    };
    this.#paths = paths.map(({ops, pts, rule, family, mark}) => {
      const path = new Path2D();
      let point = 0;
      for (const operation of ops) {
        switch (operation) {
          case 0: path.moveTo(pts[point++], pts[point++]); break;
          case 1: path.lineTo(pts[point++], pts[point++]); break;
          case 2: path.quadraticCurveTo(pts[point++], pts[point++], pts[point++], pts[point++]); break;
          case 3: path.bezierCurveTo(pts[point++], pts[point++], pts[point++], pts[point++], pts[point++], pts[point++]); break;
          case 4: path.closePath(); break;
          default: throw new Error(`Unknown QVP operation: ${operation}`);
        }
      }
      return {path, rule, family, mark};
    });
    const wordPaths = new Uint8Array(this.#paths.length);
    for (const {firstPath, nPaths} of words) {
      for (let path = firstPath; path < firstPath + nPaths; path++) {
        if (wordPaths[path]) throw new Error("Overlapping QVP word paths");
        wordPaths[path] = 1;
      }
    }
    this.#decorationPaths = Array.from(wordPaths, (owned, path) => owned ? -1 : path)
      .filter((path) => path >= 0);
  }

  fit(canvas: {width: number; height: number}, padding = 0): QvpView {
    const scale = Math.min(
      (canvas.width - 2 * padding) / this.width,
      (canvas.height - 2 * padding) / this.height,
    );
    return {
      scale,
      x: (canvas.width - this.width * scale) / 2,
      y: (canvas.height - this.height * scale) / 2,
    };
  }

  draw(
    ctx: CanvasRenderingContext2D,
    {scale = 1, x = 0, y = 0, ink = "#231f20", highlight = [], band = "#bedbfa", hideWaqf = false}: DrawOptions & {
      highlight?: number[];
      band?: string;
    } = {},
  ) {
    ctx.save();
    ctx.setTransform(scale, 0, 0, scale, x, y);
    ctx.fillStyle = band;
    for (const index of highlight) {
      const box = this.words[index]?.box;
      if (box) ctx.fillRect(box[0], box[1], box[2] - box[0], box[3] - box[1]);
    }
    ctx.fillStyle = ink;
    for (const {path, rule, family, mark} of this.#paths) {
      if (hideWaqf && isQvpPausePath(family, mark)) continue;
      ctx.fill(path, rule);
    }
    ctx.restore();
  }

  drawWords(ctx: CanvasRenderingContext2D, wordIndices: number[], options: DrawOptions = {}) {
    const pathIndices: number[] = [];
    const seen = new Set<number>();
    for (const index of wordIndices) {
      if (!Number.isInteger(index) || index < 0 || index >= this.words.length) {
        throw new RangeError(`Invalid QVP word index: ${index}`);
      }
      if (seen.has(index)) continue;
      seen.add(index);
      const {firstPath, nPaths} = this.words[index];
      for (let path = firstPath; path < firstPath + nPaths; path++) pathIndices.push(path);
    }
    this.#drawPaths(ctx, pathIndices, options);
  }

  drawDecorations(ctx: CanvasRenderingContext2D, options: DrawOptions = {}) {
    this.#drawPaths(ctx, this.#decorationPaths, options);
  }

  #drawPaths(
    ctx: CanvasRenderingContext2D,
    pathIndices: number[],
    {scale = 1, x = 0, y = 0, ink = "#231f20", hideWaqf = false}: DrawOptions = {},
  ) {
    ctx.save();
    ctx.setTransform(scale, 0, 0, scale, x, y);
    ctx.fillStyle = ink;
    for (const index of pathIndices) {
      const {path, rule, family, mark} = this.#paths[index];
      if (hideWaqf && isQvpPausePath(family, mark)) continue;
      ctx.fill(path, rule);
    }
    ctx.restore();
  }

  hitTest(x: number, y: number) {
    return this.words.find(({box: [x0, y0, x1, y1]}) =>
      x >= x0 && x <= x1 && y >= y0 && y <= y1) ?? null;
  }
}
