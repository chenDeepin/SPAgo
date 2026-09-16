#!/usr/bin/env python3
"""Give an X11 window the input focus, for the screen-reader pass (B-44).

Why this exists: a screen reader announces only the *active* window. On this
workstation no window owned `_NET_ACTIVE_WINDOW` while the pass ran, so Orca
processed focus events and stayed silent ("[frame | …] lacks state active").
`--force-renderer-accessibility` gets Chrome to expose its tree; this gets the
window the activation that makes a reader speak about it.

Needs only python3's stdlib (ctypes) and libX11 — no third-party package. A
window manager that refuses focus-stealing may ignore the request; the caller
verifies by reading `_NET_ACTIVE_WINDOW` back.

Usage: x11-focus.py <window-id-in-hex>   (0x4000004)
       x11-focus.py --title-match "SPAgo - Google Chrome"
"""
import ctypes
import os
import re
import subprocess
import sys


def window_ids_for(title_match, class_match):
    """Windows whose title contains `title_match` and whose WM_CLASS contains
    `class_match`. The class test matters because the app's title does not carry
    "Google Chrome" for every view, while the human's editor window title does
    contain "SPAgo"."""
    out = subprocess.run(
        ["xwininfo", "-root", "-tree"], capture_output=True, text=True, check=False
    ).stdout
    found = []
    for line in out.splitlines():
        # xwininfo -tree prints:  0x… "title": ("class-instance" "Class")
        m = re.match(r'\s+(0x[0-9a-f]+) "([^"]*)"\s*:?\s*\(([^)]*)\)', line)
        if not m:
            continue
        if title_match.lower() in m.group(2).lower() and class_match.lower() in m.group(3).lower():
            found.append(m.group(1))
    return found


def focus(win_id):
    xlib = ctypes.CDLL("libX11.so.6")
    xlib.XOpenDisplay.restype = ctypes.c_void_p
    display = xlib.XOpenDisplay(None)
    if not display:
        raise SystemExit("cannot open the X display")
    display = ctypes.c_void_p(display)
    # RevertToParent, CurrentTime
    xlib.XSetInputFocus(display, ctypes.c_ulong(win_id), 2, 0)
    xlib.XRaiseWindow(display, ctypes.c_ulong(win_id))
    xlib.XFlush(display)


def active_window():
    out = subprocess.run(
        ["xprop", "-root", "_NET_ACTIVE_WINDOW"], capture_output=True, text=True, check=False
    ).stdout
    m = re.search(r"#\s*(0x[0-9a-f]+|0x0)", out)
    return m.group(1) if m else "unknown"


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    if sys.argv[1] == "--title-match":
        ids = window_ids_for(sys.argv[2], os.environ.get("AT_WINDOW_CLASS", "google-chrome"))
        if not ids:
            raise SystemExit(f"no window matching {sys.argv[2]!r}")
        win_id = int(ids[0], 16)
    else:
        win_id = int(sys.argv[1], 16)
    focus(win_id)
    act = active_window()
    print(f"focused 0x{win_id:x}; _NET_ACTIVE_WINDOW={act}")
    raise SystemExit(0 if act == hex(win_id) else 2)


if __name__ == "__main__":
    main()
