#!/usr/bin/env python3
"""Report whether WMA (ASF) files carry Windows Media DRM.

Usage: wma_drm_check.py <dir>

DRM-protected ASF files declare it in the header object with one of the
encryption object GUIDs below; unprotected files have none of them.
"""
import os
import struct
import sys
import uuid

ASF_HEADER = uuid.UUID("75B22630-668E-11CF-A6D9-00AA0062CE6C").bytes_le
DRM_OBJECTS = {
    "WMDRM v1 (Content Encryption)": "2211B3FB-BD23-11D2-B4B7-00C04FB4AB59",
    "WMDRM v7+ (Extended Content Encryption)": "298AE614-2622-4C17-B935-DAE07EE9289C",
    "PlayReady (Advanced Content Encryption)": "43058533-6981-49E6-9B74-AD12CB86D58C",
}
DRM_OBJECTS = {k: uuid.UUID(v).bytes_le for k, v in DRM_OBJECTS.items()}


def check(path):
    with open(path, "rb") as f:
        head = f.read(24)
        if len(head) < 24 or head[:16] != ASF_HEADER:
            return "NOT ASF (unexpected format)"
        size = struct.unpack("<Q", head[16:24])[0]
        header = head + f.read(min(size, 16 << 20) - 24)
    found = [name for name, guid in DRM_OBJECTS.items() if guid in header]
    return "PROTECTED: " + ", ".join(found) if found else "not protected"


def main():
    root = sys.argv[1]
    results = []
    for dirpath, _, files in os.walk(root):
        for name in files:
            if name.lower().endswith(".wma"):
                p = os.path.join(dirpath, name)
                results.append((check(p), os.path.relpath(p, root)))
    for status, rel in sorted(results):
        print(f"{status:<55} {rel}")
    prot = sum(s.startswith("PROTECTED") for s, _ in results)
    print(f"\n{len(results)} WMA files checked, {prot} protected")


if __name__ == "__main__":
    main()
