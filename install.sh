#!/bin/sh
# Install FindNow for the current user (Ubuntu / Debian, GNOME).
# Usage: ./install.sh [--hotkey '<Control>space'] [--double-tap]
#
#   --hotkey ACCEL   GNOME shortcut that opens FindNow (default: <Control>space).
#                    You can change it later in FindNow → ⚙ Settings.
#   --double-tap     Also allow double-tap hotkeys such as Ctrl, Ctrl. This installs a
#                    udev rule that lets the logged-in user read keyboard events
#                    (the same access a desktop session already has), so FindNow can
#                    see modifier taps that GNOME shortcuts cannot express.
set -e
cd "$(dirname "$0")"

HOTKEY='<Control>space'
HOTKEY_GIVEN=no
DOUBLE_TAP=no
while [ $# -gt 0 ]; do
  case "$1" in
    --hotkey) HOTKEY="${2:?--hotkey needs a value}"; HOTKEY_GIVEN=yes; shift 2 ;;
    --double-tap) DOUBLE_TAP=yes; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done
SHARE="$HOME/.local/share/findnow"
UNITS="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

echo "→ Installing dependencies (may ask for your sudo password)…"
sudo apt-get install -y python3-gi gir1.2-gtk-4.0 libglib2.0-bin plocate python3-evdev

if [ "$DOUBLE_TAP" = yes ]; then
  echo "→ Allowing the logged-in user to read keyboards (for double-tap hotkeys)…"
  echo 'SUBSYSTEM=="input", KERNEL=="event*", ENV{ID_INPUT_KEYBOARD}=="1", TAG+="uaccess"' \
    | sudo tee /etc/udev/rules.d/70-findnow-keyboard.rules >/dev/null
  sudo udevadm control --reload-rules
  sudo udevadm trigger --subsystem-match=input --action=change
fi

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

if command -v gsettings >/dev/null 2>&1 && \
   gsettings list-schemas | grep -qx org.gnome.settings-daemon.plugins.media-keys; then
  echo "→ Binding $HOTKEY (change it any time in FindNow → ⚙ Settings)…"
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
else
  echo "  Not on GNOME: bind a hotkey to '$HOME/.local/bin/findnow' in your desktop's keyboard settings."
fi

# an explicit --hotkey replaces the one saved in FindNow's settings
if [ "$HOTKEY_GIVEN" = yes ]; then
  python3 - "$HOTKEY" <<'PY'
import json, os, sys
d = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "findnow")
p = os.path.join(d, "shortcuts.json")
data = {"settings": {}, "shortcuts": []}
if os.path.exists(p):
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        data = {"settings": {}, "shortcuts": data}
data.setdefault("settings", {})["hotkey"] = sys.argv[1]
os.makedirs(d, exist_ok=True)
with open(p, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
PY
fi

# FindNow re-applies the hotkey saved in its settings on start, so restart it last
systemctl --user enable findnow.service
systemctl --user restart findnow.service
echo "✓ Installed. Open FindNow with your hotkey (Ctrl+Space by default) — change it in ⚙ Settings."
