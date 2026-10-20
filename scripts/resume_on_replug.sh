#!/bin/bash
# Run the copy and keep it going across player freezes: whenever the player
# hangs, wait until it has been restarted and plugged in again (it shows up
# on USB with a new device number), then resume. Ends when the copy finishes.
# Args: <kit dir> <dest dir> [now|wait] [only=ID,... | salvage=ID,...]
#   now      start as soon as the player is on USB (default)
#   wait     the player plugged in now is frozen: wait for it to be restarted
#   only=    retry just these songs, one at a time and once each
#   salvage= recover the rest of these songs past the spots that hang the
#            player (zen_salvage.py), with as many restarts as that takes
S=$1; DEST=$2; L="$DEST/copy-progress.log"
devnum() { lsusb -d 041e:411e | awk '{ print $4 + 0; exit }'; }
# Wait for a player on USB that is not the frozen one (device number $last).
await() {
  until [ -n "$(devnum)" ] && [ "$(devnum)" != "$last" ]; do sleep 2; done
  sleep 15  # let it finish docking before talking to it
}
run() {  # <script> [arg]; returns the script's exit code
  echo "=== run started $(date +%T), turbo off, 3 s between songs, 0.3 s between MiB chunks${2:+, ${1%.py} $2} ===" >> "$L"
  python3 -I -u "$S/scripts/$1" "$S/tracks.txt" "$S/bin/njb_bulkget" "$DEST" ${2:+"$2"} >> "$L" 2>&1
}
hung() {
  last=$(devnum)
  echo "player stopped responding: restart it (battery out, main menu) and plug it in again ($(date +%T))" >> "$L"
}
last=
[ "$3" = wait ] && last=$(devnum)

case $4 in
only=*)
  # One song per run, so a song that hangs the player cannot hold up the
  # others. It is not tried again: it would just hang the player again.
  rc=0
  for id in $(tr , ' ' <<< "${4#only=}"); do
    await; run zen_extract.py "only=$id"; r=$?
    if [ $r -eq 2 ]; then hung; else last=; fi
    [ $r -eq 0 ] || rc=1
  done
  exit $rc ;;
salvage=*) script=zen_salvage.py arg=${4#salvage=} ;;
*) script=zen_extract.py arg= ;;
esac
# Each run picks up where the previous one stopped.
while :; do
  await; run $script "$arg"; rc=$?
  [ $rc -eq 2 ] || exit $rc
  hung
done
