#!/usr/bin/env python3
"""Recover songs that hang the player at a damaged spot, around that spot.

Usage: zen_salvage.py <tracks.txt> <njb_bulkget binary> <dest dir>
                      [fill= | probe=]ID,ID,...

zen_extract.py keeps the start of such a song, up to where the player hung,
as "<Title> (partial).<ext>". This reads the rest of the song in 8 KiB
requests instead of libnjb's 1 MiB ones, so a bad spot on the drive stalls
only the 8 KiB block it is in, starting at the first byte still missing.
When the player hangs, that block is marked bad and the next run (after the
player has been restarted) carries on after it. Each recovered piece is
written into the partial file at its own position, so bad blocks are left
as zeros: MP3 decoders skip over them, and in a WAV they are silence.

Bad blocks with less than 1 MiB of readable data between them mean a
damaged area, which would cost a restart every few hundred KiB. There the
next run jumps ahead instead: 1/256 of the song past the bad block, twice
as far for each further bad block in the area, up to 1/16 of the song, so
that even a song damaged all the way through takes about 20 restarts.
Once past the area, a read usually runs to the end of the song. The
skipped ranges are recorded in salvage.json, so they can be tried again
later.

When every byte has been read, marked bad or skipped, the file becomes
"<Title>.<ext>" if nothing is missing, or "<Title> (gaps).<ext>", and the
log says how much is missing and where.

fill=ID,... goes back over finished songs and reads everything that is
neither read nor known to be bad, skipped ranges included, without
jumping: it recovers the most, at one restart per bad block found. To save
restarts, each read also stops short of blocks predicted to be bad. On the
drive we tried, bad blocks recurred along a cycle, probably a scratch
crossing every track: when nearly all known bad blocks fit a cycle, its
other positions are predicted; otherwise the blocks one or two times the
most common spacing away from a bad block are. A prediction is kept once
made.

probe=ID,... then reads the predicted blocks one at a time, the least
suspected first: a block that turns out readable is recovered, one that is
really bad costs a restart.

Progress is kept in <dest>/salvage.json, so this is simply run again after
every restart (resume_on_replug.sh with salvage=, fill= or probe= does).
Exit codes: 0 all listed songs finished, 2 player stopped responding,
3 could not open the player.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zen_extract import (CHUNK_PAUSE_MS, SONG_PAUSE_S, parse_tracks,  # noqa: E402
                         plan_paths, player_present, read_reply, unlist)

REQUEST = 0x2000      # bytes per request: one block, the most precise
AREA = 0x100000       # bad blocks with less data read between them than this
                      # belong to one damaged area
FIRST_JUMP = 256      # in a damaged area, jump 1/256 of the song past a bad
MAX_JUMP = 16         # block, twice as far for each further one, up to 1/16


def position(offset, t):
    """Approximate play position (m:ss) of a byte offset in the track."""
    secs = int(offset / int(t["FILE SIZE"]) * int(t.get("LENGTH") or 0))
    return f"{secs // 60}:{secs % 60:02d}"


def first_missing(ranges, size):
    """The first byte of [0, size) not in any of the ranges, or None."""
    pos = 0
    for a, b in sorted(ranges):
        if a > pos:
            break
        pos = max(pos, b)
    return pos if pos < size else None


def holes(have, size):
    """The byte ranges of [0, size) not covered by the `have` ranges."""
    out, pos = [], 0
    for a, b in sorted(have):
        if a > pos:
            out.append([pos, a])
        pos = max(pos, b)
    if pos < size:
        out.append([pos, size])
    return out


def read_between(have, a, b):
    """How many bytes of [a, b) have been read."""
    return (b - a) - sum(max(0, min(y, b) - max(x, a))
                         for x, y in holes(have, b))


def cycle(blocks):
    """(period, phase) in blocks such that nearly all bad blocks lie within
    2 blocks after phase + k * period, or None. The period need not be a
    whole number of blocks: a drive track is rarely a multiple of 8 KiB."""
    blocks = tuple(blocks)
    if blocks in _cycles:
        return _cycles[blocks]
    best = (0, 0.0, 0.0)
    if len(blocks) >= 6:
        periods = {round((y - x) / k, 3) for n, x in enumerate(blocks)
                   for y in blocks[n + 1:]
                   for k in range(max(1, (y - x) // 64), (y - x) // 8 + 1)}
        for per in periods:
            for phase in {x % per for x in blocks}:
                hits = sum(1 for x in blocks if (x - phase) % per < 2)
                # on a tie, the longer period: fewer blocks to skip
                if (hits, per) > best[:2]:
                    best = (hits, per, phase)
    found = best[1:] if best[0] >= 0.9 * len(blocks) and best[0] >= 6 else None
    _cycles[blocks] = found
    return found


_cycles = {}


def suspects(s, size):
    """Unread blocks predicted to be bad: those on the cycle the bad blocks
    lie on if there is one, else one or two times the most common spacing
    between known bad blocks away from one of them."""
    blocks = sorted({a // REQUEST for a, _ in s["bad"]})
    done = s["have"] + s["bad"]
    cyc = cycle(blocks)
    if cyc:
        per, phase = cyc
        return [[x * REQUEST, min((x + 1) * REQUEST, size)]
                for a, e in holes(done, size)
                for x in range(a // REQUEST, (e + REQUEST - 1) // REQUEST)
                if (x - phase) % per < 2]
    count = {}
    for n, x in enumerate(blocks):
        for y in blocks[n + 1:]:
            count[y - x] = count.get(y - x, 0) + 1
    # A spacing counts with its multiples: bad blocks two tracks apart too.
    score = {d: sum(count.get(k * d, 0) for k in (1, 2, 3))
             for d in range(8, 129)}
    d, n = min(score.items(), key=lambda kv: (-kv[1], kv[0]), default=(0, 0))
    if n < 4:
        return []
    hits = {}
    for b in blocks:
        for k in (-2, -1, 1, 2):
            hits[b + k * d] = hits.get(b + k * d, 0) + 1
    out = []
    # The least suspected first: predicted by the fewest bad blocks.
    for b in sorted(hits, key=lambda b: (hits[b], b)):
        a, e = b * REQUEST, min((b + 1) * REQUEST, size)
        if 0 <= a < size and read_between(done, a, e) == 0:
            out.append([a, e])
    return out


def predicted(s, size):
    """Blocks predicted to be bad, now or on an earlier run, that are not
    read or found bad yet, the least suspected first. A prediction is kept
    once made: new bad blocks can change the most common spacing, and a
    block must not be read just because it is no longer predicted."""
    now = suspects(s, size)
    done = s["have"] + s["bad"]
    s["suspected"] = [r for r in s.get("suspected", []) + now
                      if read_between(done, *r) == 0]
    s["suspected"] = [r for n, r in enumerate(s["suspected"])
                      if r not in s["suspected"][:n]]
    rank = {a: n for n, (a, _) in enumerate(now)}
    return sorted(s["suspected"], key=lambda r: rank.get(r[0], -1))


def read_piece(proc, t, target, start, end):
    """Ask the copier for bytes start..end-1 of track t and write what
    arrives in its place in the file `target`. Returns the copier's reply
    (None if the player froze) and how many bytes arrived."""
    i, size = t["ID"], int(t["FILE SIZE"])
    part = target + ".part"
    if os.path.exists(part):
        os.remove(part)
    try:
        proc.stdin.write(f"{i}\t{size}\t{part}\t{start}\t{end}\n")
        proc.stdin.flush()
        left = end - start  # small requests are slower: 150 kB/s floor
        reply = read_reply(proc, 60 + left / 150_000
                           + left / 2**20 * CHUNK_PAUSE_MS / 1000,
                           (f"OK {i}", f"ERR {i}"), part)
    except BrokenPipeError:
        reply = ""
    if reply is None:
        proc.kill()
        proc.wait()
    got = os.path.getsize(part) if os.path.exists(part) else 0
    got = min(got, end - start)  # the last request may go a little past end
    if got:
        with open(target, "r+b" if os.path.exists(target) else "wb") as f, \
                open(part, "rb") as piece:
            f.seek(start)
            f.write(piece.read(got))
    if os.path.exists(part):
        os.remove(part)
    return reply, got


def main():
    tracks_txt, bulkget, dest, ids = sys.argv[1:5]
    probe = ids.startswith("probe=")
    fill = probe or ids.startswith("fill=")
    ids = ids.split("=")[-1].split(",")
    songs = {t["ID"]: (t, p) for t, p in
             plan_paths(parse_tracks(tracks_txt), dest)}
    hung_file = os.path.join(dest, "hung-tracks.txt")
    state_file = os.path.join(dest, "salvage.json")
    state = json.load(open(state_file)) if os.path.exists(state_file) else {}

    def save():
        with open(state_file + ".tmp", "w") as f:
            json.dump(state, f, indent=1)
        os.replace(state_file + ".tmp", state_file)

    todo = []
    for i in ids:
        t, path = songs[i]
        if os.path.exists(path) and os.path.getsize(path) == int(t["FILE SIZE"]):
            continue  # copied whole after all
        root, ext = os.path.splitext(path)
        partial = f"{root} (partial){ext}"
        if i not in state:
            got = os.path.getsize(partial) if os.path.exists(partial) else 0
            state[i] = {"have": [[0, got]] if got else []}
        state[i].setdefault("bad", [])
        state[i].setdefault("skipped", [])
        if fill:
            size = int(t["FILE SIZE"])
            skip = [] if probe else predicted(state[i], size)
            if state[i].get("done") and holes(state[i]["have"] + state[i]["bad"]
                                              + skip, size):
                todo.append((t, path, f"{root} (gaps){ext}", state[i]))
        elif not state[i].get("done"):
            todo.append((t, path, partial, state[i]))
    save()
    if not todo:
        print("SALVAGE: nothing left to do", flush=True)
        return
    # Songs with fewer known bad blocks first, so one song with many bad
    # blocks does not hold the others back for a restart each.
    todo.sort(key=lambda song: len(song[3]["bad"]))

    proc = subprocess.Popen([bulkget, str(CHUNK_PAUSE_MS), str(REQUEST)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            text=True, bufsize=1)
    if read_reply(proc, 60, ("READY",)) != "READY":
        proc.kill()
        print("PLAYER NOT RESPONDING: could not open it, reconnect and re-run")
        sys.exit(3)

    hung = False
    for n, (t, path, target, s) in enumerate(todo, 1):
        i, size = t["ID"], int(t["FILE SIZE"])
        root, ext = os.path.splitext(path)
        while True:
            if fill:
                # The first stretch neither read nor known to be bad, read
                # only up to the next bad block.
                sus = predicted(s, size)
                missing = holes(s["have"] + s["bad"] + ([] if probe else sus),
                                size)
                if not missing:
                    break
                if probe:  # predicted blocks least suspected first
                    rank = {a: r for r, (a, _) in enumerate(sus)}
                    missing.sort(key=lambda m: rank.get(m[0], -1))
                start, end = missing[0]
            else:
                start = first_missing(s["have"] + s["bad"] + s["skipped"], size)
                end = size
            time.sleep(SONG_PAUSE_S)
            reply, got = read_piece(proc, t, target, start, end)
            if got:
                s["have"].append([start, start + got])
            # After any failed request the player has always hung on the
            # next one.
            hung = reply != f"OK {i}"
            stop = start + got
            status = f"read {got // 1024} KiB at {position(start, t)}"
            if stop < end:
                s["bad"].append([stop, min(stop + REQUEST, size)])
                status = (f"bad block at byte {stop} ({position(stop, t)}), "
                          f"after {got} more bytes")
            if stop < end and not fill:
                # Count the bad blocks of the damaged area this one belongs
                # to, and jump past it if there are more.
                area, edge = 1, stop
                for a, _ in sorted(s["bad"], reverse=True):
                    if a < edge:
                        if read_between(s["have"], a + REQUEST, edge) > AREA:
                            break
                        area, edge = area + 1, a
                if area > 1:
                    jump = min((size // FIRST_JUMP) << (area - 2),
                               size // MAX_JUMP)
                    jump = max(REQUEST, jump // REQUEST * REQUEST)
                    a = min(stop + REQUEST, size)
                    s["skipped"].append([a, min(a + jump, size)])
                    status += f"; damaged area, skipping {jump // 1024} KiB"
            save()
            if not fill or hung:
                break
            print(f"[fill {n}/{len(todo)}] {status}: "
                  f"{os.path.relpath(path, dest)}", flush=True)
        covered = s["have"] + s["bad"] + ([] if probe else predicted(s, size)
                                          if fill else s["skipped"])
        if first_missing(covered, size) is None:
            s["done"] = True
            missing = holes(s["have"], size)
            if not missing:
                os.replace(target, path)
                unlist(hung_file, i)
                status = "RECOVERED COMPLETELY"
            elif s["have"]:
                with open(target, "r+b") as f:
                    if f.seek(0, os.SEEK_END) < size:
                        f.truncate(size)
                if target != f"{root} (gaps){ext}":
                    os.replace(target, f"{root} (gaps){ext}")
                lost = sum(b - a for a, b in missing)
                status = (f"SALVAGED {100 - 100 * lost / size:.1f}%, "
                          f"{len(missing)} gaps: " + ", ".join(
                              f"{(b - a) / 1024:.0f} KiB at {position(a, t)}"
                              for a, b in missing[:8])
                          + (", ..." if len(missing) > 8 else ""))
            else:
                status = "NOTHING RECOVERED"
            save()
        print(f"[salvage {n}/{len(todo)}] {status}: {os.path.relpath(path, dest)}",
              flush=True)
        if hung:
            if reply is not None:
                time.sleep(3)
                if not player_present():
                    print("player disconnected", flush=True)
            print("\nPLAYER NOT RESPONDING: restart it and re-run to continue",
                  flush=True)
            break

    if hung:
        proc.kill()
    else:
        proc.stdin.close()
        proc.wait(timeout=30)
    sys.exit(2 if hung else 0)


if __name__ == "__main__":
    main()
