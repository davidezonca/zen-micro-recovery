#!/usr/bin/env python3
"""Hide the gaps in a salvaged WAV file by filling them from the audio around them.

Usage: fill_wav_gaps.py <salvage.json> <track id> <in.wav> <out.wav>

zen_salvage.py leaves the blocks it could not read as zeros, which in a WAV
is a short silence, heard as a dropout. For each gap this continues the
waveform from both sides by repeating its last period (the lag at which the
audio best matches itself) and crossfades from the left continuation into
the right one across the gap. Gaps of a few tens of milliseconds then
usually go unnoticed. The gaps are the byte ranges not recovered, as
recorded in salvage.json. Only 16-bit PCM WAV files; needs numpy.
"""
import json
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zen_salvage import holes  # noqa: E402

CONTEXT = 4096    # frames of audio on each side to take the period from
MATCH = 1024      # frames compared when looking for the period
MIN_PERIOD_S = 0.002
MAX_PERIOD_S = 0.025


def wav_layout(data):
    """(channels, sample rate, offset of the samples, number of frames)."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        sys.exit("not a WAV file (no RIFF header)")
    pos, fmt = 12, None
    while pos + 8 <= len(data):
        cid, n = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", data[pos + 8:pos + 24])
        elif cid == b"data":
            break
        pos += 8 + n + (n & 1)
    if fmt is None or fmt[0] != 1 or fmt[5] != 16:
        sys.exit("only 16-bit PCM WAV files are supported")
    channels, rate = fmt[1], fmt[2]
    start = pos + 8
    return channels, rate, start, (len(data) - start) // (2 * channels)


def period(x, rate):
    """The lag, in frames, at which the mono signal x best matches itself."""
    lo = int(MIN_PERIOD_S * rate)
    hi = min(int(MAX_PERIOD_S * rate), len(x) - MATCH)
    if hi <= lo:
        return max(1, len(x) // 2)
    ref = x[-MATCH:]
    best, lag = -np.inf, lo
    for t in range(lo, hi + 1):
        seg = x[-MATCH - t:-t]
        score = np.dot(ref, seg) / (np.linalg.norm(seg) * np.linalg.norm(ref) + 1e-9)
        if score > best:
            best, lag = score, t
    return lag


def main():
    state_file, tid, src, dst = sys.argv[1:5]
    data = bytearray(open(src, "rb").read())
    channels, rate, start, frames = wav_layout(data)
    have = json.load(open(state_file))[tid]["have"]
    audio = np.frombuffer(bytes(data[start:start + frames * 2 * channels]),
                          dtype="<i2").reshape(frames, channels).astype(float)

    # Byte ranges not recovered -> whole frames; the header is not audio.
    frame = 2 * channels
    gaps = []
    for a, b in holes(have, len(data)):
        f0 = max(0, -(-(a - start) // frame))
        f1 = min(frames, (b - start) // frame)
        if f1 > f0:
            gaps.append((f0, f1))

    for n, (f0, f1) in enumerate(gaps):
        size = f1 - f0
        nxt = gaps[n + 1][0] if n + 1 < len(gaps) else frames
        left = audio[max(0, f0 - CONTEXT):f0]          # already filled
        right = audio[f1:min(nxt, f1 + CONTEXT)]
        i = np.arange(size)
        parts = []
        if len(left) > 2 * MIN_PERIOD_S * rate:
            t = period(left.mean(axis=1), rate)
            parts.append(left[len(left) - t + (i % t)])
        if len(right) > 2 * MIN_PERIOD_S * rate:
            t = period(right[::-1].mean(axis=1), rate)
            parts.append(right[(i - size) % t])
        if len(parts) == 2:
            w = (0.5 - 0.5 * np.cos(np.pi * (i + 0.5) / size))[:, None]
            audio[f0:f1] = (1 - w) * parts[0] + w * parts[1]
        elif parts:
            audio[f0:f1] = parts[0]

    out = np.clip(np.round(audio), -32768, 32767).astype("<i2").tobytes()
    data[start:start + len(out)] = out
    open(dst, "wb").write(data)
    print(f"filled {len(gaps)} gaps, {sum(b - a for a, b in gaps) / rate:.2f} s "
          f"of audio, in {dst}")


if __name__ == "__main__":
    main()
