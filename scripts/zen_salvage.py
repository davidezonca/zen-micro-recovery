#!/usr/bin/env python3
"""Recover songs that hang the player at a damaged spot, around that spot.

Usage: zen_salvage.py <tracks.txt> <njb_bulkget binary> <dest dir> ID,ID,...

zen_extract.py keeps the start of such a song, up to where the player hung,
as "<Title> (partial).<ext>". This reads the rest of the song in 8 KiB
requests instead of libnjb's 1 MiB ones, so a bad spot on the drive stalls
only the 8 KiB block it is in, starting at the first byte still missing.
When the player hangs, that block is marked bad and the next run (after the
player has been restarted) carries on after it. Each recovered piece is
written into the partial file at its own position, so bad blocks are left
as zeros: MP3 decoders skip over them, and in a WAV they are silence. A bad
block right after another one marks 4 times as much as bad, so a large
damaged area costs only a few restarts.

When every byte has been read or marked bad, the file becomes
"<Title>.<ext>" if nothing was bad, or "<Title> (gaps).<ext>", and the log
says where the gaps are. Progress is kept in <dest>/salvage.json, so this is
simply run again after every restart (resume_on_replug.sh salvage=... does).
Exit codes: 0 all listed songs finished, 2 player stopped responding.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zen_extract import (CHUNK_PAUSE_MS, SONG_PAUSE_S, parse_tracks,  # noqa: E402
                         plan_paths, player_present, read_reply, unlist)

REQUEST = 0x2000  # bytes per request: one block, the most precise
GROWTH = 4        # how much more to mark bad when bad blocks are adjacent


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


def main():
    tracks_txt, bulkget, dest, ids = sys.argv[1:5]
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
    for i in ids.split(","):
        t, path = songs[i]
        if os.path.exists(path) and os.path.getsize(path) == int(t["FILE SIZE"]):
            continue  # copied whole after all
        root, ext = os.path.splitext(path)
        partial = f"{root} (partial){ext}"
        if i not in state:
            got = os.path.getsize(partial) if os.path.exists(partial) else 0
            state[i] = {"have": [[0, got]] if got else []}
        state[i].setdefault("bad", [])
        if not state[i].get("done"):
            todo.append((t, path, partial, state[i]))
    save()
    if not todo:
        print("SALVAGE: nothing left to do", flush=True)
        return

    proc = subprocess.Popen([bulkget, str(CHUNK_PAUSE_MS), str(REQUEST)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            text=True, bufsize=1)
    if read_reply(proc, 60, ("READY",)) != "READY":
        proc.kill()
        print("PLAYER NOT RESPONDING: could not open it, reconnect and re-run")
        sys.exit(2)

    hung = False
    for n, (t, path, partial, s) in enumerate(todo, 1):
        i, size = t["ID"], int(t["FILE SIZE"])
        start = first_missing(s["have"] + s["bad"], size)
        part = path + ".part"
        if os.path.exists(part):
            os.remove(part)
        time.sleep(SONG_PAUSE_S)
        try:
            proc.stdin.write(f"{i}\t{size}\t{part}\t{start}\n")
            proc.stdin.flush()
            left = size - start  # small requests are slower: 150 kB/s floor
            reply = read_reply(proc, 60 + left / 150_000
                               + left / 2**20 * CHUNK_PAUSE_MS / 1000,
                               (f"OK {i}", f"ERR {i}"))
        except BrokenPipeError:
            reply = ""
        if reply is None:
            proc.kill()
            proc.wait()
        # Put the piece that arrived in its place in the partial file.
        got = os.path.getsize(part) if os.path.exists(part) else 0
        if got:
            with open(partial, "r+b" if os.path.exists(partial) else "wb") as f, \
                    open(part, "rb") as piece:
                f.seek(start)
                f.write(piece.read())
            s["have"].append([start, start + got])
        if os.path.exists(part):
            os.remove(part)
        # After any failed request the player has always hung on the next one.
        hung = reply != f"OK {i}"
        stop = start + got
        if stop < size:
            # The request that stalled is bad; if the one before it was bad
            # too, the damaged area is bigger: mark more of it.
            length = REQUEST
            if not got:
                length = max([GROWTH * (b - a) for a, b in s["bad"] if b == stop]
                             + [REQUEST])
            s["bad"].append([stop, min(stop + length, size)])
            status = (f"bad block at byte {stop} ({position(stop, t)}), "
                      f"after {got} more bytes")
        if first_missing(s["have"] + s["bad"], size) is None:
            s["done"] = True
            root, ext = os.path.splitext(path)
            if not s["bad"]:
                os.replace(partial, path)
                unlist(hung_file, i)
                status = "RECOVERED COMPLETELY"
            elif s["have"]:
                with open(partial, "r+b") as f:
                    if f.seek(0, os.SEEK_END) < size:
                        f.truncate(size)
                os.replace(partial, f"{root} (gaps){ext}")
                status = "SALVAGED, missing " + ", ".join(
                    f"{(b - a) / 1024:.0f} KiB at {position(a, t)}"
                    for a, b in sorted(s["bad"]))
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
