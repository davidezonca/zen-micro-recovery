#!/bin/bash
# Wait for the frozen Zen Micro to be unplugged and plugged back in, then
# resume the copy. Args: <kit dir> <dest dir> [now|wait] [only=ID,...]
# With "now", a player that is already plugged in is used as is; a 4th
# argument is passed on to zen_extract.py.
S=$1; DEST=$2; L="$DEST/copy-progress.log"
present() { lsusb -d 041e:411e >/dev/null 2>&1; }
if [ "$3" != now ]; then
  while present; do sleep 2; done
  echo "player unplugged $(date +%T), waiting for it to come back" >> "$L"
fi
until present; do sleep 2; done
sleep 15  # let it finish docking before talking to it
echo "=== run started $(date +%T), turbo off, 3 s between songs, 0.3 s between MiB chunks${4:+, $4} ===" >> "$L"
exec python3 -I -u "$S/scripts/zen_extract.py" "$S/tracks.txt" "$S/bin/njb_bulkget" "$DEST" ${4:+"$4"} >> "$L" 2>&1
