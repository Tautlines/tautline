import { staticFile } from "remotion";

export const MINERVIT_MIDNIGHT_PULSE = "builtin:minervit-midnight-pulse";

const SAMPLE_RATE = 22050;
const WAV_HEADER_BYTES = 44;
const TWO_PI = Math.PI * 2;
const cache = new Map<string, string>();

const encodeBase64 = (bytes: Uint8Array): string => {
  let binary = "";
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
  }
  return btoa(binary);
};

const writeAscii = (view: DataView, offset: number, value: string): void => {
  for (let index = 0; index < value.length; index += 1) {
    view.setUint8(offset + index, value.charCodeAt(index));
  }
};

const clamp = (value: number, min: number, max: number): number => Math.max(min, Math.min(max, value));

const envelope = (position: number, length: number, falloff: number): number => {
  const safeLength = Math.max(length, 0.001);
  const phase = clamp(position / safeLength, 0, 1);
  return Math.exp(-phase * falloff);
};

const midnightPulseSample = (time: number, durationSeconds: number): number => {
  const roots = [110, 146.83, 98, 130.81];
  const root = roots[Math.floor(time / 3.5) % roots.length];
  const slow = 0.78 + Math.sin(TWO_PI * 0.055 * time) * 0.18;
  const pad =
    Math.sin(TWO_PI * root * time) * 0.18 +
    Math.sin(TWO_PI * root * 1.5 * time + 0.7) * 0.13 +
    Math.sin(TWO_PI * root * 2 * time + 1.4) * 0.07;
  const beatPosition = time % 0.5;
  const pulse = Math.sin(TWO_PI * root * 2 * time) * envelope(beatPosition, 0.5, 7.5) * 0.12;
  const downbeatPosition = time % 2;
  const low = Math.sin(TWO_PI * (48 + 18 * envelope(downbeatPosition, 2, 6)) * time) * envelope(downbeatPosition, 2, 9) * 0.18;
  const tickPosition = time % 0.25;
  const tick = Math.sin(TWO_PI * (880 + Math.sin(time * 4) * 40) * time) * envelope(tickPosition, 0.25, 16) * 0.025;
  const fadeIn = clamp(time / 1.4, 0, 1);
  const fadeOut = clamp((durationSeconds - time) / 1.4, 0, 1);
  return clamp((pad * slow + pulse + low + tick) * fadeIn * fadeOut * 0.55, -1, 1);
};

const createMidnightPulseDataUrl = (durationSeconds: number): string => {
  const sampleCount = Math.ceil(durationSeconds * SAMPLE_RATE);
  const dataBytes = sampleCount * 2;
  const buffer = new ArrayBuffer(WAV_HEADER_BYTES + dataBytes);
  const view = new DataView(buffer);

  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, SAMPLE_RATE, true);
  view.setUint32(28, SAMPLE_RATE * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, "data");
  view.setUint32(40, dataBytes, true);

  for (let sample = 0; sample < sampleCount; sample += 1) {
    const time = sample / SAMPLE_RATE;
    const value = Math.round(midnightPulseSample(time, durationSeconds) * 32767);
    view.setInt16(WAV_HEADER_BYTES + sample * 2, value, true);
  }

  return `data:audio/wav;base64,${encodeBase64(new Uint8Array(buffer))}`;
};

export const resolveMusicSrc = (musicUrl: string, durationInFrames: number, fps: number): string => {
  const trimmed = musicUrl.trim();
  if (trimmed.toLowerCase() === MINERVIT_MIDNIGHT_PULSE) {
    const durationSeconds = Math.max(12, durationInFrames / fps + 0.75);
    const key = `${MINERVIT_MIDNIGHT_PULSE}:${durationSeconds.toFixed(2)}`;
    const cached = cache.get(key);
    if (cached) return cached;
    const generated = createMidnightPulseDataUrl(durationSeconds);
    cache.set(key, generated);
    return generated;
  }
  if (/^(https?:|data:|blob:)/i.test(trimmed)) {
    return trimmed;
  }
  return staticFile(trimmed.replace(/^\/+/, ""));
};
