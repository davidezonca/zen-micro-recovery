# Creative Zen Micro music recovery on modern Linux

Tools and notes for copying the music off an old **Creative Zen Micro** MP3
player on a current Linux system. They keep working even when the player's
hard drive is failing and the player keeps freezing partway through, and
they can recover most of a file that sits on damaged parts of the drive.

> **This repository is entirely AI-generated.** The code, the libnjb patches,
> the scripts and this README were written by an AI coding assistant (Claude,
> made by Anthropic, running in Claude Code) during an interactive recovery
> over three days in October 2026. A person handled the player (about a
> hundred unplugs and battery pulls, menus, cables), reported what its screen
> showed and decided what to try. Everything was tested on a single Zen Micro
> and a single laptop, so read the code before you run it.

## Is this for you?

- Your player is a Creative Zen Micro (USB ID `041e:411e`) with Creative's
  original firmware. It uses Creative's own "PDE" protocol, not MTP. libnjb
  also supports other Nomad Jukebox and Zen models, which may work too, but
  only the Zen Micro was tested.
- `lsusb` lists the player, but your file manager, Rhythmbox or other MTP
  tools show nothing.
- Your distribution no longer ships libnjb (Fedora 44 doesn't).
- libnjb fails or times out on a USB 3 (xHCI) port, and the kernel logs
  `xhci_hcd: Trying to add endpoint 0x2 without dropping it`.
- The player freezes partway through a copy and ignores the computer until
  you unplug it or take the battery out.
- The player is stuck on the Creative logo. Start with
  [Step 1](#step-1-get-the-player-to-boot-rescue-mode).

## Step 1: get the player to boot (Rescue Mode)

When we started, the player turned on once and then stopped at the Creative
logo. A stuck player never shows up on USB, whatever cable or port you use,
because it only talks to the computer after it has loaded its software from
its hard drive.

The player has a built-in Rescue Mode. These are Creative's support steps, as
quoted in a forum post by Fogel70 on SweClockers (31 Dec 2005, [source][swec]):

> 1. Make sure that battery is charged.
> 2. Detach your player from the computer, and ensure that it is turned off.
> 3. Remove the battery.
> 4. Move and hold the Power button to the Power On position and re-insert the
>    battery to the Zen Micro. Hold the Power button until the Recovery Mode
>    appears.
>
> The following options will be displayed:
>
> - Clean Up (Performs a disk scan on the players hard disk, it will not affect music files)
> - Format All (Formats the players hard disk - Note: all contents will be lost)
> - Reload Firmware (Reloads the Operating System on the Jukebox)
> - Reboot (Reboots the device)

[swec]: https://www.sweclockers.com/forum/post/6132398

What we did and saw:

- **Clean Up** fixed the boot. After it finished, **Reboot** brought up the
  normal main menu, all the music was still there, and the player appeared on
  USB.
- **Never choose Format All**: it erases all the music.
- We didn't try **Reload Firmware** and don't recommend it while you're
  rescuing music. If the drive is failing, rewriting the system software on it
  can leave the player unable to start at all.
- If Clean Up freezes, or the drive clicks repeatedly, the drive is probably
  failing. Each power-on can make that worse, so think about removing the
  drive and imaging it instead.

## Step 2: build the tools

Requirements:

- Linux on x86_64. Tested on Fedora 44 with kernel 7.2, connected to a USB 3
  (xHCI) port.
- `gcc`, `make`, `patch`, `python3` (3.8 or later) and `lsusb` (usbutils).
- The libusb 0.1 runtime library: `libusb-compat-0.1` on Fedora,
  `libusb-0.1-4` on Debian/Ubuntu.
- The libusb 0.1 headers (`usb.h`). If they aren't installed, `build.sh` on
  Fedora downloads `libusb-compat-0.1-devel` with `dnf download` and unpacks
  it locally (this needs `rpm2cpio` and `cpio`), so you don't need root. On
  other distributions, install the libusb 0.1 development package (for
  example `libusb-dev`; untested).
- Optional: `numpy` for `fill_wav_gaps.py`, `ffmpeg` to check files.

```sh
git clone https://github.com/davidezonca/zen-micro-recovery
cd zen-micro-recovery
./build.sh
```

This builds libnjb 2.2.7 with [two small patches](#whats-in-this-repository)
into `njb/`, and the copier into `bin/njb_bulkget`. Nothing is installed
system-wide.

**USB permissions.** On Fedora a desktop user can use the player without
root: the udev hardware database marks its USB ID as a media player
(`ID_MEDIA_PLAYER=1`), and `70-uaccess.rules` gives the logged-in user
access to media players. If the tools report no device or a permission error
on your system, add this udev rule and plug the player in again:

```
# /etc/udev/rules.d/60-creative-zen-micro.rules
SUBSYSTEM=="usb", ATTR{idVendor}=="041e", ATTR{idProduct}=="411e", TAG+="uaccess"
```

## Step 3: copy the music

1. Turn the player on, wait for its main menu, then plug it in. Its screen
   shows "Docked" while a program is talking to it.
2. Check that it answers: `njb/bin/njb-handshake`
3. Save its track list: `njb/bin/njb-tracks > tracks.txt`
4. Start the copy, and follow it in a second terminal. The watcher carries on
   by itself after every freeze, once you have unplugged the player and
   plugged it in again:

   ```sh
   DEST=~/Music/"Zen Micro"
   mkdir -p "$DEST"
   scripts/resume_on_replug.sh "$PWD" "$DEST"        # start now, resume after each freeze
   tail -f "$DEST/copy-progress.log"
   ```

   Songs are saved as `<Artist>/<Album>/<Title>.<ext>`. Use `wait` as the
   third argument if the player plugged in now is already frozen. To copy
   without the watcher, run
   `scripts/zen_extract.py tracks.txt bin/njb_bulkget "$DEST"` and run it
   again after each freeze; songs already copied are skipped.
5. When everything else is copied, retry the songs that failed (their IDs
   are in `hung-tracks.txt`), one at a time:

   ```sh
   scripts/resume_on_replug.sh "$PWD" "$DEST" now only=65540,66108
   ```

   A song that copies is taken off the problem list and its partial file is
   deleted. If it fails again, the longer of the partial copies is kept.
6. Check the WMA files for DRM: `scripts/wma_drm_check.py "$DEST"`

**When the player freezes.** The log says so about 20 s after the last data
arrived. Unplug the cable and plug it in again: the "Docked" screen goes away
and the next run starts 5 s after the player is back. If it still doesn't
answer (the log says "could not open it" three times), unplug it, take the
battery out for a few seconds, turn the player on, wait for the main menu and
plug it in again.

## Step 4: recover the songs that still freeze the player

These steps need one unplug per bad block found, so start with the songs
you care about most. Each runs through the watcher, which continues after
every replug until it's done:

```sh
scripts/resume_on_replug.sh "$PWD" "$DEST" now salvage=ID,ID   # 1. read around the bad spots
scripts/resume_on_replug.sh "$PWD" "$DEST" now fill=ID,ID      # 2. go back for what was skipped
scripts/resume_on_replug.sh "$PWD" "$DEST" now probe=ID,ID     # 3. try the blocks predicted bad
```

1. **salvage** reads each song in 8 KiB requests from the first byte still
   missing. When the player freezes, that 8 KiB block is marked bad, and the
   next run continues after it. Where bad blocks come with less than 1 MiB of
   good data between them, it jumps ahead instead, further each time (from
   1/256 to 1/16 of the song), so even a song that is damaged all the way
   through takes about 20 replugs. The song ends up as
   `<Title> (gaps).<ext>`: full length, with zeros where nothing could be
   read.
2. **fill** reads everything that was skipped, without jumping, and stops
   short of known bad blocks and of blocks predicted to be bad (see
   [below](#5-bad-blocks-follow-the-drives-tracks)).
3. **probe** reads the predicted blocks one by one. Readable ones are
   recovered; each really bad one costs a replug, and for us about half were.
4. For WAV files, `fill_wav_gaps.py` makes a copy in which each gap is
   filled from the audio around it, so short dropouts are no longer heard:

   ```sh
   scripts/fill_wav_gaps.py "$DEST/salvage.json" ID "song (gaps).wav" "song (gaps filled).wav"
   ```

5. A WAV whose first block is bad has lost its header. It can be read as
   raw PCM: work out the format from its size and length (`FILE SIZE` and
   `LENGTH` in `tracks.txt`; 192,000 bytes per second is 48 kHz 16-bit
   stereo, 176,400 is 44.1 kHz), then for example
   `ffmpeg -f s16le -ar 48000 -ac 2 -i "song (gaps).wav" "song.wav"`.

MP3 players skip over the zeroed gaps with a short dropout and need nothing
more. Files that are salvaged keep their ID in `hung-tracks.txt`.

**Files written to the destination folder:**

| File | What it is |
|---|---|
| `copy-progress.log` | Progress, errors and battery level of every run. |
| `manifest.csv` | Every track handled by the last copy run, with its status and path (`manifest-retry.csv` for `only=` runs). |
| `hung-tracks.txt` | IDs of songs that froze the player or failed. The copy skips them until you retry them with `only=`. |
| `<Title> (partial).<ext>` | The part of a failed song that arrived before the freeze. A cut-off MP3 still plays up to the cut. |
| `<Title> (gaps).<ext>` | A salvaged song: full length, with zeros where the player could not read. |
| `salvage.json` | For each salvaged song, the byte ranges read, found bad, skipped and predicted bad. |

## What's in this repository

| Path | What it is |
|---|---|
| `src/libnjb-2.2.7.tar.gz` | The unmodified libnjb 2.2.7 release, from [SourceForge](https://downloads.sourceforge.net/project/libnjb/libnjb/2.2.7/libnjb-2.2.7.tar.gz) (sha256 `ccbcfc870bdc10ad7a144f81a340b61bad74a6f00f77cf08db5866332668d2b6`). It's kept here because the project is no longer maintained. |
| `src/libnjb-skip-set-configuration.patch` | Removes libnjb's `usb_set_configuration()` call, which breaks the connection on xHCI controllers. |
| `src/libnjb-request-size.patch` | Lets a program choose how much of a file libnjb asks the player for per request (1 MiB by default). |
| `build.sh` | Builds the patched libnjb and the copier into `njb/` and `bin/`, without root. |
| `scripts/njb_bulkget.c` | A small C helper that opens the player once and downloads many tracks in that one session: whole, or a byte range of them. |
| `scripts/zen_extract.py` | Runs the copy: names the files, resumes, notices freezes, keeps partial files and records problem songs. |
| `scripts/zen_salvage.py` | Recovers damaged songs around the blocks that freeze the player (salvage, fill and probe). |
| `scripts/resume_on_replug.sh` | Runs any of the above again after every freeze, once the player has been plugged back in. |
| `scripts/fill_wav_gaps.py` | Fills the gaps in a salvaged WAV from the audio around them. |
| `scripts/wma_drm_check.py` | Reports whether WMA files carry Windows Media DRM. |

Everything here only reads from the player. `build.sh` deletes the libnjb
sample programs that write to, delete from or reflash the player
(`njb-sendtr`, `njb-deltr`, `njb-fwupgrade` and others), so nothing built
here can change what's on it.

## How it works, and what we learned

### 1. Talking to the player

- **It isn't MTP.** The Zen Micro's original firmware uses Creative's own
  protocol, and only libnjb implements it. libmtp lists the USB ID but can't
  talk to the player. libnjb 2.2.7 (2007) was the last release, and several
  distributions have dropped it, so `build.sh` builds it from source.
- **The xHCI patch.** When libnjb opens the player, it selects USB
  configuration 1. On this laptop's USB 3 (xHCI) controller that call failed
  and left the bulk endpoints broken: every transfer after it timed out, and
  the kernel logged `Trying to add endpoint 0x2 without dropping it`. The
  player has only one configuration and the kernel has already selected it,
  so the patch removes the call.
- **libnjb prints to stdout.** Some libnjb errors are printed to stdout,
  where they mixed with `njb_bulkget`'s replies and got the wrong songs
  blamed. `njb_bulkget` keeps its replies on a private copy of stdout, sends
  everything else to stderr, and every reply carries the track ID.

### 2. The bulk copy

- **One session for all songs.** libnjb's `njb-gettr` sample opens and
  captures the player separately for every song. Each capture makes the
  player switch to its "Docked" screen and back, and after a few dozen songs
  its firmware hung. `njb_bulkget` captures the player once and downloads
  everything in that session.
- **Turbo mode off.** By default libnjb reads 16 KiB blocks ("turbo mode"),
  and its documentation says "a few (very few) devices will react badly on
  turbo mode". With 8 KiB blocks the copy ran for hundreds of songs between
  freezes, against a few dozen before, but some of the early freezes were on
  damaged songs, so it's unclear how much turbo mode mattered.
- **Pacing.** The copier waits 3 s between songs and 0.3 s per MiB, for about
  0.8 MB/s overall. It's not proven that this helps: the freezes that
  remained were tied to particular songs.
- **Stop after a read error.** After a failed request the player always hung
  on the next one, so the copier stops instead of blaming the next song, and
  it copies the neighbours of known-bad songs last (failures came in pairs of
  adjacent track IDs, probably files stored next to each other).
- **Battery.** `njb_bulkget` logs the battery level. A weak battery wasn't
  the cause of the freezes.

### 3. Freezes, and getting the player back

- A frozen player stops sending data but doesn't report an error, and
  libnjb's USB timeout is 10 ms per byte, about 80 s per 8 KiB block. The
  scripts instead watch the file being written and call the player frozen
  after **20 s without new data** (blocks normally arrive many times a
  second).
- A frozen player doesn't answer a **USB port reset** (`USBDEVFS_RESET`):
  the kernel reports "device not accepting address". Turning the port off
  through sysfs (`/sys/bus/usb/devices/.../disable`) didn't help either:
  on our laptop the port stays powered.
- **Unplugging the cable** was usually enough: the player drops the "Docked"
  screen and can be plugged in again straight away. A few times it then
  showed up on USB but timed out on every command, and needed the battery
  out.
- After a replug the watcher waits 5 s, and retries opening the player twice
  before calling it frozen. Once, the desktop session's access to the newly
  plugged player wasn't applied (`usb_open: Permission denied`); another
  replug fixed it.

### 4. Small requests: 8 KiB instead of 1 MiB

libnjb always reads a track from byte 0, asking the player for 1 MiB at a
time by offset and then reading that chunk in blocks.
`libnjb-request-size.patch` makes the request size settable, and
`njb_bulkget` can start and stop at any offset.

- **Small requests read what large ones couldn't.** Two WAV files failed with
  a read error on their very first 1 MiB request. Read in 8 KiB requests,
  their first bad block turned out to be 4.5 MB and 14.5 MB into the file.
- **With 1 MiB requests, freezes cluster oddly.** They all came within the
  first 584 KiB of a request, and several offsets within the request
  repeated across different files. We don't know why.
- **With 8 KiB requests, a freeze marks the bad block itself.** Every
  mid-file freeze point we re-read with 8 KiB requests froze again at the
  same block, and the block after it read fine. Bad blocks never came back
  readable.
- Reading from an offset that is a multiple of 8 KiB runs at about
  0.68 MB/s. From an unaligned offset it's 0.18 MB/s. Every offset and range
  read was checked byte for byte against copies of undamaged songs.

### 5. Bad blocks follow the drive's tracks

In damaged files the bad blocks were not random. In one file they fell on a
cycle of 10.44 blocks (85 KiB, probably one track of the drive): all 21 bad
blocks lie within 2 blocks of that cycle, though only about a third of the
cycle's positions were actually bad. In another, the bad blocks came
alternately 9 and 26 blocks apart, two bad positions in each cycle of 35
blocks, and all 35 of them also fit a cycle of 8.82 blocks. No two bad
blocks were ever adjacent. This looks like a scratch crossing the tracks.

`zen_salvage.py fill=` uses this. When at least 90% of the known bad blocks
(and at least 6) fit a cycle of any length between 8 and 64 blocks, not
necessarily a whole number, the other positions on the cycle are predicted
bad. Otherwise, blocks one or two times the most common spacing away from a
bad block are. Predicted blocks are skipped, and `probe=` tries them later.
A prediction is kept once made, because new bad blocks can change the best
fit and a block shouldn't be read just because it dropped out of it.

### 6. Filling the gaps in WAV files

`fill_wav_gaps.py` continues the waveform into each gap from both sides,
repeating its last period (the lag between 2 and 25 ms at which the audio
best matches itself), and crossfades from one continuation to the other
across the gap. On a synthetic two-tone signal with 46 ms gaps, the error
inside the gaps dropped from 100% (silence) to 4% (RMS). Only bytes inside
the gaps are changed.

## Results

On our player (firmware 1.11.1): 1,048 files, 5.72 GB (971 MP3, 67 WMA,
10 WAV).

| Step | Result |
|---|---|
| Bulk copy | 1,029 files copied whole; 19 froze the player or failed |
| Retries, one at a time | 3 more copied; 8 froze again, 5 of them at exactly the same byte as before |
| Left with bad blocks | 16 files (5 were salvaged; the other 11 weren't tried) |
| WMA DRM check | 67 files, none protected, all decode completely |

The five salvaged files (percentages are of the file's bytes):

| File | Format, size | Bulk copy | salvage | fill | probe | Bad blocks | Replugs |
|---|---|---|---|---|---|---|---|
| A | WAV, 63.8 MB | 0% (first request failed) | 99.97% | – | – | 2 | 2 |
| B | WAV, 49.1 MB | 0% (first block bad) | 96.7% | 99.75% | – | 10 | 10 |
| C | WAV, 59.2 MB | 0% (first request failed) | 78.5% | 96.3% | – | 21 | 21 |
| D | MP3, 5.0 MB | 49.9% | 99.5% | – | – | 3 | 3 |
| E | MP3, 6.8 MB | 23.7% | 45.5% | 94.2% | 95.8% | 35 | 34 |

- **File C** shows the effect of prediction. With whole-block spacings,
  fill gained 0.1–0.8 MB per replug. Once fractional cycles were detected,
  the last two runs read about 8 MB with a single freeze. The 248 blocks
  left unread (2 MB, 16% of the stretch salvage had skipped) are predicted
  bad. Its 152 gaps, mostly 46 ms each and 12.5 s in total, were then filled
  with `fill_wav_gaps.py`.
- **File E**: before prediction, fill gained 100–200 KiB per replug. With
  it, the first run read about 1 MB before its next freeze. Of its 25
  predicted blocks, probe found 12 readable and 13 bad.
- **File B** needed its header rebuilt, because its first block was bad.
- The log records 92 freezes over 115 runs, each cleared by an unplug or a
  battery pull.

## Limitations

- Tested on one Zen Micro and one laptop.
- A file stored on a damaged part of the drive is recovered with gaps where
  the player can't read it. Every bad block costs an unplug, so a heavily
  damaged file takes patience.
- Reading only. Nothing here sends music or firmware to the player.
- The scripts look for the Zen Micro's USB ID `041e:411e` (`lsusb -d` in
  `zen_extract.py` and `resume_on_replug.sh`). For another model, change it
  there.

## Licence

The files written for this repository are under the MIT licence (see
`LICENSE`). libnjb, bundled in `src/`, keeps its own BSD licence (see
`LICENSE` and `AUTHORS` inside the tarball), and the patches are offered under
the same BSD licence. The Rescue Mode steps above are quoted from the cited
forum post, which relays Creative's support article.
