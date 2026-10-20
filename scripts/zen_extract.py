#!/usr/bin/env python3
"""Copy every track off a Creative Zen Micro in a single libnjb session.

Usage: zen_extract.py <tracks.txt> <njb_bulkget binary> <dest dir>
                     [limit | only=ID,ID,...]

tracks.txt is the output of njb/bin/njb-tracks (libnjb's `tracks` sample).
Files are written as <dest>/<Artist>/<Album>/<Title>.<ext>. Re-running skips
tracks that already exist with the expected size, so an interrupted copy can
simply be resumed.
only=... retries just those tracks, including ones listed in hung-tracks.txt.
Exit codes: 0 all copied, 1 some tracks failed, 2 player stopped responding.
"""
import csv
import os
import re
import select
import subprocess
import sys
import time

EXT = {"MP3": "mp3", "WMA": "wma", "WAV": "wav"}
# Pacing, slower but steadier: rest between songs and between the 1 MiB
# chunks the player reads from its drive.
SONG_PAUSE_S = 3
CHUNK_PAUSE_MS = 300


def parse_tracks(path):
    tracks, cur = [], {}
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if line.startswith("----"):
            if cur:
                tracks.append(cur)
            cur = {}
        elif ": " in line or line.endswith(":"):
            key, _, val = line.partition(":")
            cur[key.strip()] = val.strip()
    if cur.get("ID"):
        tracks.append(cur)
    return tracks


def clean(name, fallback):
    name = re.sub(r"[/\x00-\x1f]", "-", name or "")
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    return (name or fallback)[:150]


def read_reply(proc, timeout, expected):
    """Return the first copier line found in `expected`, "" if the copier
    exited, or None if no expected line arrives within `timeout` seconds.
    Unexpected lines are skipped so stray output cannot desync replies."""
    deadline = time.time() + timeout
    while (left := deadline - time.time()) > 0:
        ready, _, _ = select.select([proc.stdout], [], [], left)
        if not ready:
            return None
        line = proc.stdout.readline()
        if not line:
            return ""
        if line.strip() in expected:
            return line.strip()
    return None


def player_present():
    return subprocess.run(["lsusb", "-d", "041e:411e"],
                          capture_output=True).returncode == 0


def main():
    tracks_txt, bulkget, dest = sys.argv[1:4]
    arg = sys.argv[4] if len(sys.argv) > 4 else ""
    only = set(arg[5:].split(",")) if arg.startswith("only=") else None
    limit = int(arg) if arg and only is None else None
    tracks = parse_tracks(tracks_txt)[:limit]
    os.makedirs(dest, exist_ok=True)

    used, plan = set(), []
    for t in tracks:
        ext = EXT.get(t.get("CODEC", ""), t.get("CODEC", "bin").lower())
        d = os.path.join(dest, clean(t.get("ARTIST"), "Unknown Artist"),
                         clean(t.get("ALBUM"), "Unknown Album"))
        stem = clean(t.get("TITLE"), f"Track {t['ID']}")
        path = os.path.join(d, f"{stem}.{ext}")
        if path in used:
            path = os.path.join(d, f"{stem} [{t['ID']}].{ext}")
        used.add(path)
        plan.append((t, path))
    if only:  # filtered after naming so collision suffixes stay the same
        plan = [tp for tp in plan if tp[0]["ID"] in only]

    # Tracks that failed or hung the player are remembered here and skipped
    # on later runs, so an unreadable file cannot block the whole copy; they
    # are retried at the end by removing their IDs from this file.
    hung_file = os.path.join(dest, "hung-tracks.txt")
    hung = set(open(hung_file).read().split()) if os.path.exists(hung_file) else set()
    listed = set(hung)
    if only:
        hung -= only

    # Failures come in pairs of neighbouring track IDs (likely adjacent damaged
    # spots on the drive), so copy the neighbours of known-bad tracks last.
    ids = sorted(int(t["ID"]) for t, _ in plan)
    pos = {v: i for i, v in enumerate(ids)}
    risky = {ids[j] for b in hung if int(b) in pos
             for j in range(max(0, pos[int(b)] - 2), min(len(ids), pos[int(b)] + 3))}
    plan.sort(key=lambda tp: int(tp[0]["ID"]) in risky)

    proc = subprocess.Popen([bulkget, str(CHUNK_PAUSE_MS)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, bufsize=1)
    if read_reply(proc, 60, ("READY",)) != "READY":
        proc.kill()
        print("PLAYER NOT RESPONDING: could not open it, reconnect and re-run")
        sys.exit(2)

    total_bytes = sum(int(t["FILE SIZE"]) for t, _ in plan)
    done_bytes, copied_bytes, failed = 0, 0, []
    aborted, start = False, time.time()
    manifest = open(os.path.join(dest, "manifest-retry.csv" if only
                                 else "manifest.csv"), "w", newline="")
    w = csv.writer(manifest)
    w.writerow(["id", "artist", "album", "title", "codec", "size", "status", "path"])

    for n, (t, path) in enumerate(plan, 1):
        size = int(t["FILE SIZE"])
        status = "skipped (already present)"
        if os.path.exists(path) and os.path.getsize(path) == size:
            pass
        elif t["ID"] in hung:
            status = "SKIPPED (failed before, retry at the end)"
            failed.append((t["ID"], path, "failed or hung the player on an earlier run"))
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            part = path + ".part"
            root, ext = os.path.splitext(path)
            partial = f"{root} (partial){ext}"
            status, err = "FAILED", ""
            # libnjb's own USB timeouts are effectively unbounded, so cap each
            # transfer at a generous 250 kB/s floor. No immediate retry.
            if os.path.exists(part):
                os.remove(part)
            time.sleep(SONG_PAUSE_S)
            try:
                proc.stdin.write(f"{t['ID']}\t{size}\t{part}\n")
                proc.stdin.flush()
                pauses = size / 2**20 * CHUNK_PAUSE_MS / 1000
                reply = read_reply(proc, 60 + size / 250_000 + pauses,
                                   (f"OK {t['ID']}", f"ERR {t['ID']}"))
            except BrokenPipeError:
                reply = ""
            if reply is None:
                err, aborted = "timeout, player hung", True
                proc.kill()
                proc.wait()
            elif reply.startswith("OK") and os.path.exists(part) \
                    and os.path.getsize(part) == size:
                os.replace(part, path)
                status = "ok"
                copied_bytes += size
                if os.path.exists(partial):
                    os.remove(partial)
                if t["ID"] in listed:
                    listed.discard(t["ID"])
                    with open(hung_file) as f:
                        keep = [i for i in f.read().split() if i != t["ID"]]
                    with open(hung_file, "w") as f:
                        f.write("".join(i + "\n" for i in keep))
            else:
                # After a read error the player has always hung on the next
                # request, and once it drops off USB every request fails at
                # once; either way stop rather than blame the next songs.
                err, aborted = "read error" if reply else "copier exited", True
                time.sleep(3)
                if not player_present():
                    err = "player disconnected"
            # A truncated MP3 still plays up to the cut, so keep the longest
            # piece that has arrived on any attempt.
            got = os.path.getsize(part) if os.path.exists(part) else 0
            if status == "FAILED" and got:
                err += f" (got first {got} bytes)"
                if got > (os.path.getsize(partial) if os.path.exists(partial) else 0):
                    os.replace(part, partial)
            if os.path.exists(part):
                os.remove(part)
            if status == "FAILED":
                failed.append((t["ID"], path, err))
                status = f"FAILED ({err}; will retry at the end)"
                if t["ID"] not in listed:
                    listed.add(t["ID"])
                    with open(hung_file, "a") as f:
                        f.write(t["ID"] + "\n")
        done_bytes += size
        w.writerow([t["ID"], t.get("ARTIST"), t.get("ALBUM"), t.get("TITLE"),
                    t.get("CODEC"), size, status, os.path.relpath(path, dest)])
        manifest.flush()
        rate = copied_bytes / (time.time() - start) / 1e6
        print(f"[{n}/{len(plan)}] {done_bytes/1e9:.2f}/{total_bytes/1e9:.2f} GB "
              f"{rate:.1f} MB/s {status}: {os.path.relpath(path, dest)}",
              flush=True)
        if aborted:
            print("\nPLAYER NOT RESPONDING: reconnect it and re-run to resume",
                  flush=True)
            break

    if aborted:
        proc.kill()
    else:
        proc.stdin.close()
        proc.wait(timeout=30)
    manifest.close()
    print(f"\nDONE: {n - len(failed)} of {n} processed tracks ok, "
          f"{len(failed)} failed, {(time.time() - start)/60:.1f} min", flush=True)
    for tid, path, err in failed:
        print(f"FAILED {tid} {path}: {err}", flush=True)
    sys.exit(2 if aborted else 1 if failed else 0)


if __name__ == "__main__":
    main()
