#!/bin/sh
if [ "$1" = "remove" ] || [ "$1" = "purge" ] || [ "$1" = "0" ]; then
  command -v update-alternatives >/dev/null 2>&1 && {
    update-alternatives --remove x-www-browser /usr/bin/iuk-browser 2>/dev/null || true
    update-alternatives --remove gnome-www-browser /usr/bin/iuk-browser 2>/dev/null || true
  }
fi
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
exit 0
