#!/bin/bash
# Build the patched libnjb and the single-session copier into njb/ and bin/.
# No root needed: gcc, make, patch and the libusb-0.1 runtime library are
# enough. The libusb-0.1 headers (usb.h) come from the system if installed;
# otherwise, on Fedora, the -devel RPM is fetched with `dnf download` (or
# taken from src/ if already there) and unpacked into build/.
set -euo pipefail
P=$(cd "$(dirname "$0")" && pwd)
B="$P/build"
rm -rf "$B" "$P/njb" "$P/bin"
mkdir -p "$B/usbdev" "$P/bin"

USB="$B/usbdev/usr"
if [ ! -f /usr/include/usb.h ]; then
  rpm=$(ls "$P"/src/libusb-compat-0.1-devel-*.rpm 2>/dev/null | head -n1 || true)
  if [ -z "$rpm" ]; then
    if ! command -v dnf >/dev/null; then
      echo "libusb-0.1 headers (usb.h) not found: install your distribution's" \
           "libusb-0.1 development package (e.g. libusb-dev) and re-run" >&2
      exit 1
    fi
    dnf download -q --repo=fedora --repo=updates --arch "$(uname -m)" \
      --destdir "$B" libusb-compat-0.1-devel
    rpm=$(ls "$B"/libusb-compat-0.1-devel-*.rpm | head -n1)
  fi
  (cd "$B/usbdev" && rpm2cpio "$rpm" | cpio -idm --quiet)
  # no early exit in awk: with pipefail, ldconfig's SIGPIPE would abort the build
  lib=$(ldconfig -p | awk '$1 == "libusb-0.1.so.4" && !n++ { print $NF }')
  [ -n "$lib" ] || { echo "libusb-0.1.so.4 runtime library not found" >&2; exit 1; }
  mkdir -p "$USB/lib64"
  ln -sf "$lib" "$USB/lib64/libusb.so"
fi

tar xzf "$P/src/libnjb-2.2.7.tar.gz" -C "$B"
patch -d "$B/libnjb-2.2.7" -p1 < "$P/src/libnjb-skip-set-configuration.patch"

mkdir -p "$B/obj" && cd "$B/obj"
"$B/libnjb-2.2.7/configure" --prefix="$P/njb" --build="$(uname -m)-pc-linux-gnu" \
  CPPFLAGS="-I$USB/include" LDFLAGS="-L$USB/lib64" \
  CFLAGS="-O2 -std=gnu89" > configure.log
make -j"$(nproc)" > make.log
make install > install.log

# Drop the sample tools that write to or reflash the player, so nothing in
# this kit can modify it by accident.
cd "$P/njb/bin"
rm -f njb-delfile njb-deltr njb-fwupgrade njb-pl njb-sendfile njb-sendtr \
  njb-setowner njb-setpbm njb-settime njb-tagtr

gcc -O2 -Wall -o "$P/bin/njb_bulkget" "$P/scripts/njb_bulkget.c" \
  -I"$P/njb/include" -I"$USB/include" -L"$P/njb/lib" -lnjb \
  -Wl,-rpath,"$P/njb/lib"
echo "built: $P/bin/njb_bulkget and read-only tools in $P/njb/bin"
