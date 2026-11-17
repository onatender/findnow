#!/bin/sh
# Install FindNow for the current user (Ubuntu / Debian, GNOME).
# Usage: ./install.sh [--hotkey '<Control>space']
set -e
cd "$(dirname "$0")"

HOTKEY='<Control>space'
[ "${1:-}" = "--hotkey" ] && [ -n "${2:-}" ] && HOTKEY="$2"
SHARE="$HOME/.local/share/findnow"
UNITS="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

echo "→ Installing dependencies (may ask for your sudo password)…"
sudo apt-get install -y python3-gi gir1.2-gtk-4.0 libglib2.0-bin plocate

echo "→ Copying files…"
mkdir -p "$SHARE" "$HOME/.local/bin" "$UNITS"
install -m 755 findnow.py index.sh "$SHARE/"
install -m 755 findnow "$HOME/.local/bin/findnow"
install -m 644 systemd/findnow.service systemd/findnow-index.service \
               systemd/findnow-index.timer "$UNITS/"

echo "→ Building the file index and starting services…"
systemctl --user daemon-reload
"$SHARE/index.sh" || echo "  (index build failed; the timer will retry in 15 minutes)"
systemctl --user enable --now findnow-index.timer
systemctl --user enable findnow.service
systemctl --user restart findnow.service

if command -v gsettings >/dev/null 2>&1 && \
   gsettings list-schemas | grep -qx org.gnome.settings-daemon.plugins.media-keys; then
  echo "→ Binding $HOTKEY…"
  B=org.gnome.settings-daemon.plugins.media-keys
  P=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/findnow/
  python3 - "$B" "$P" <<'PY'
import ast, subprocess, sys
schema, path = sys.argv[1], sys.argv[2]
cur = subprocess.run(["gsettings", "get", schema, "custom-keybindings"],
                     capture_output=True, text=True).stdout.strip()
paths = ast.literal_eval(cur.replace("@as ", "")) if cur else []
if path not in paths:
    paths.append(path)
    subprocess.run(["gsettings", "set", schema, "custom-keybindings", str(paths)], check=True)
PY
  gsettings set "$B.custom-keybinding:$P" name 'FindNow'
  gsettings set "$B.custom-keybinding:$P" command "$HOME/.local/bin/findnow"
  gsettings set "$B.custom-keybinding:$P" binding "$HOTKEY"
  echo "✓ Installed. Press $HOTKEY to open FindNow."
else
  echo "✓ Installed. Not on GNOME: bind a hotkey to '$HOME/.local/bin/findnow' in your desktop's keyboard settings."
fi
