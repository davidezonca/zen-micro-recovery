#!/bin/bash
# Run the copy and keep it going across player freezes: whenever the player
# hangs, wait until it has been restarted and plugged in again (it shows up
# on USB with a new device number), then resume. Ends when the copy finishes.
# Args: <kit dir> <dest dir> [now|wait] [only=ID,...]
#   now   start as soon as the player is on USB (default)
#   wait  the player plugged in now is frozen: wait for it to be restarted
#   only= retry just these songs, once (passed on to zen_extract.py)
S=$1; DEST=$2; L="$DEST/copy-progress.log"
devnum() { lsusb -d 041e:411e | awk '{ print $4 + 0; exit }'; }
last=
[ "$3" = wait ] && last=$(devnum)
while :; do
  until [ -n "$(devnum)" ] && [ "$(devnum)" != "$last" ]; do sleep 2; done
  sleep 15  # let it finish docking before talking to it
  echo "=== run started $(date +%T), turbo off, 3 s between songs, 0.3 s between MiB chunks${4:+, $4} ===" >> "$L"
  python3 -I -u "$S/scripts/zen_extract.py" "$S/tracks.txt" "$S/bin/njb_bulkget" "$DEST" ${4:+"$4"} >> "$L" 2>&1
  rc=$?
  # Retrying the same songs again would just freeze the player again.
  [ $rc -ne 2 ] || [ -n "$4" ] && exit $rc
  last=$(devnum)
  echo "player stopped responding: restart it (battery out, main menu) and plug it in again ($(date +%T))" >> "$L"
done
