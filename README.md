# Creative Zen Micro music recovery on modern Linux

Tools and notes for copying the music off an old **Creative Zen Micro** MP3
player on a current Linux system. They keep working even when the player's
hard drive is failing and the player keeps freezing partway through.

> **This repository is entirely AI-generated.** The code, the libnjb patch,
> the scripts and this README were written by an AI coding assistant (Claude,
> made by Anthropic, running in Claude Code) during one interactive recovery
> session in October 2026. A person handled the player (battery pulls, menus,
> cables), reported what its screen showed and decided what to try. Everything
> was tested on a single Zen Micro and a single laptop, so read the code before
> you run it.

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
- The player freezes partway through a long copy and ignores the computer
  until you take the battery out.
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

```sh
git clone https://github.com/davidezonca/zen-micro-recovery
cd zen-micro-recovery
./build.sh
```

This builds libnjb 2.2.7 with [one patch](#how-it-works-and-what-we-learned)
into `njb/`, and the copier into `bin/njb_bulkget`. Nothing is installed
system-wide.

**USB permissions.** On Fedora a desktop user can use the player without
root: the udev hardware database marks its USB ID as a media player
(`ID_MEDIA_PLAYER=1`), and `70-uaccess.rules` gives the logged-in user
access to media players. If the tools
report no device or a permission error on your system, add this udev rule and
plug the player in again:

```
# /etc/udev/rules.d/60-creative-zen-micro.rules
SUBSYSTEM=="usb", ATTR{idVendor}=="041e", ATTR{idProduct}=="411e", TAG+="uaccess"
```

## Step 3: copy the music

1. Turn the player on, wait for its main menu, then plug it in. Its screen
   shows "Docked" while a program is talking to it.
2. Check that it answers: `njb/bin/njb-handshake`
3. Save its track list: `njb/bin/njb-tracks > tracks.txt`
4. Start the copy and follow it in a second terminal:

   ```sh
   DEST=~/Music/"Zen Micro"
   mkdir -p "$DEST"
   scripts/zen_extract.py tracks.txt bin/njb_bulkget "$DEST" >> "$DEST/copy-progress.log" 2>&1
   tail -f "$DEST/copy-progress.log"
   ```

   Songs are saved as `<Artist>/<Album>/<Title>.<ext>`.
5. If the player freezes, restart it (see below) and run the same command
   again. Songs already copied are skipped. To have the copy restart by
   itself after each restart:

   ```sh
   scripts/resume_on_replug.sh "$PWD" "$DEST"       # waits for you to unplug, restart and replug
   scripts/resume_on_replug.sh "$PWD" "$DEST" now   # the player is already plugged in and ready
   ```

   It reads `tracks.txt` from this directory, appends to
   `copy-progress.log` and runs one copy each time you start it.
6. When everything else is copied, retry the songs that failed, one at a
   time if you like:

   ```sh
   scripts/zen_extract.py tracks.txt bin/njb_bulkget "$DEST" only=65540,66108
   ```

   A song that copies is taken off the problem list and its partial file is
   deleted. If it fails again, the longer of the partial copies is kept.
7. Check the WMA files for DRM: `scripts/wma_drm_check.py "$DEST"`

`zen_extract.py` exits with 0 if every song was copied, 1 if some failed and
2 if the player stopped responding.

**Restarting a frozen player.** A frozen player ignores everything over USB,
including a USB port reset. Unplug it, take the battery out for a few
seconds, put it back, turn the player on, wait for the main menu and plug it
in again.

**Files written to the destination folder:**

| File | What it is |
|---|---|
| `manifest.csv` | Every track handled by the last run, with its status and path (`manifest-retry.csv` for `only=` runs). |
| `hung-tracks.txt` | IDs of songs that froze the player or failed. Later runs skip them until you retry them with `only=`. |
| `<Title> (partial).<ext>` | The part of a failed song that arrived before the freeze. A cut-off MP3 still plays up to the cut. |
| `copy-progress.log` | Progress, errors and battery level, if you redirect output there as above. |

## What's in this repository

| Path | What it is |
|---|---|
| `src/libnjb-2.2.7.tar.gz` | The unmodified libnjb 2.2.7 release, from [SourceForge](https://downloads.sourceforge.net/project/libnjb/libnjb/2.2.7/libnjb-2.2.7.tar.gz) (sha256 `ccbcfc870bdc10ad7a144f81a340b61bad74a6f00f77cf08db5866332668d2b6`). It's kept here because the project is no longer maintained. |
| `src/libnjb-skip-set-configuration.patch` | Removes libnjb's `usb_set_configuration()` call, which breaks the connection on xHCI controllers. |
| `build.sh` | Builds the patched libnjb and the copier into `njb/` and `bin/`, without root. |
| `scripts/njb_bulkget.c` | A small C helper that opens the player once and downloads many tracks in that one session. |
| `scripts/zen_extract.py` | Runs the copy: names the files, resumes, notices freezes, keeps partial files and records problem songs. |
| `scripts/resume_on_replug.sh` | Waits for the player to be restarted and plugged back in, then resumes the copy. |
| `scripts/wma_drm_check.py` | Reports whether WMA files carry Windows Media DRM. |

Everything here only reads from the player. `build.sh` deletes the libnjb
sample programs that write to, delete from or reflash the player
(`njb-sendtr`, `njb-deltr`, `njb-fwupgrade` and others), so nothing built
here can change what's on it.

## How it works, and what we learned

1. **It isn't MTP.** The Zen Micro's original firmware uses Creative's own
   protocol, and only libnjb implements it. libmtp lists the USB ID but can't
   talk to the player. libnjb 2.2.7 (2007) was the last release, and several
   distributions have dropped it, so `build.sh` builds it from source.
2. **The xHCI patch.** When libnjb opens the player, it selects USB
   configuration 1. On this laptop's USB 3 (xHCI) controller that call failed
   and left the bulk endpoints broken. Every transfer after it timed out, and
   the kernel logged `Trying to add endpoint 0x2 without dropping it`. The
   player has only one configuration and the kernel has already selected it,
   so the patch removes the call.
3. **One session for all songs.** libnjb's `njb-gettr` sample opens and
   captures the player separately for every song. Each capture makes the
   player switch to its "Docked" screen and back, and after a few dozen songs
   its firmware hung. `njb_bulkget` captures the player once and downloads
   everything in that session.
4. **Turbo mode off.** By default libnjb requests 16 KiB blocks ("turbo
   mode"), and its documentation says "a few (very few) devices will react
   badly on turbo mode". With 8 KiB blocks and a 1 s pause between songs, the
   first run copied about 500 songs before the player froze. Earlier runs with
   the defaults had frozen much sooner, but at least one of those freezes was
   on a damaged song, so it's unclear how much turbo mode mattered.
5. **Damaged songs.** The freezes that remain are tied to particular songs: a
   retry froze at exactly the same byte. They are probably bad spots on the
   player's tiny hard drive. For those songs, the copier:
   - gives up after 60 s plus 4 s per MB. libnjb's own USB timeout is 10 ms
     per byte, which is about 80 s for each 8 KiB block.
   - keeps whatever arrived as a `(partial)` file.
   - writes the song's ID to `hung-tracks.txt` and skips it on later runs.
   - copies the neighbours of known-bad songs last. Failures came in pairs of
     adjacent track IDs, probably files stored next to each other.
   - stops after a read error, because the player always hung on the next
     request anyway, and the next song shouldn't take the blame.
6. **libnjb prints to stdout.** Some libnjb errors are printed to stdout,
   where they mixed with `njb_bulkget`'s replies and got the wrong songs
   blamed. `njb_bulkget` keeps its replies on a private copy of stdout, sends
   everything else to stderr, and every reply carries the track ID.
7. **Pacing.** By default the copier waits 3 s between songs and 0.3 s between
   the 1 MiB chunks libnjb requests, for an overall speed of about 0.8 MB/s.
   It's not proven that this helps beyond turning turbo mode off, because the
   freezes we saw were tied to particular songs. You can change
   `SONG_PAUSE_S` and `CHUNK_PAUSE_MS` in `zen_extract.py`.
8. **Battery.** `njb_bulkget` logs the battery level. A weak battery wasn't
   the cause of the freezes in our case.

## WMA files and DRM

WMA files bought from online music stores in the 2000s may be protected with
Windows Media DRM, and nothing on Linux can play those. `wma_drm_check.py`
looks for the encryption objects in each file's ASF header. To confirm that a
file really plays, decode it all the way through with
`ffmpeg -v error -i song.wma -f null -`.

## Limitations

- Tested on one Zen Micro (firmware 1.11.1, 1,048 tracks, 5.7 GB) and one
  laptop.
- A song stored on a damaged part of the drive can only be copied up to the
  bad spot.
- Reading only. Nothing here sends music or firmware to the player.
- The scripts look for the Zen Micro's USB ID `041e:411e` (`lsusb -d` in
  `zen_extract.py` and `resume_on_replug.sh`). For another model, change it
  there.

## Licence

The files written for this repository are under the MIT licence (see
`LICENSE`). libnjb, bundled in `src/`, keeps its own BSD licence (see
`LICENSE` and `AUTHORS` inside the tarball), and the patch is offered under
the same BSD licence. The Rescue Mode steps above are quoted from the cited
forum post, which relays Creative's support article.
