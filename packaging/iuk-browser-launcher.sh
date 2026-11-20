#!/bin/sh
# Runs the bundled Gecko with its own profile so it never touches your normal Firefox profile.
# --class/--name make the window manager (taskbar, minimized-window list, alt-tab) match the
# StartupWMClass in iuk-browser.desktop, which is what selects the IUK Browser icon.
PROFILE="${XDG_DATA_HOME:-$HOME/.local/share}/iuk-browser/profile"
mkdir -p "$PROFILE"
exec /usr/lib/iuk-browser/firefox --no-remote --class iuk-browser --name iuk-browser --profile "$PROFILE" "$@"
