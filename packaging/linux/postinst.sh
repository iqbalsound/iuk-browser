#!/bin/sh
# Refresh icon/desktop caches and offer IUK Browser as a web browser alternative. Never fails the install.
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications 2>/dev/null || true
if command -v update-alternatives >/dev/null 2>&1; then
  update-alternatives --install /usr/bin/x-www-browser x-www-browser /usr/bin/iuk-browser 40 2>/dev/null || true
  update-alternatives --install /usr/bin/gnome-www-browser gnome-www-browser /usr/bin/iuk-browser 40 2>/dev/null || true
fi
exit 0
