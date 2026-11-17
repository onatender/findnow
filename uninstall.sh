#!/bin/sh
# Remove FindNow. Your shortcuts (~/.config/findnow) are kept; delete that folder too for a clean slate.
UNITS="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
systemctl --user disable --now findnow.service findnow-index.timer 2>/dev/null
rm -f "$UNITS/findnow.service" "$UNITS/findnow-index.service" "$UNITS/findnow-index.timer" \
      "$HOME/.local/bin/findnow"
rm -rf "$HOME/.local/share/findnow" "${XDG_CACHE_HOME:-$HOME/.cache}/findnow"
systemctl --user daemon-reload
if [ -f /etc/udev/rules.d/70-findnow-keyboard.rules ]; then
  echo "→ Removing the double-tap keyboard rule (may ask for your sudo password)…"
  sudo rm -f /etc/udev/rules.d/70-findnow-keyboard.rules
  sudo udevadm control --reload-rules
  sudo udevadm trigger --subsystem-match=input --action=change
fi

if command -v gsettings >/dev/null 2>&1 && \
   gsettings list-schemas | grep -qx org.gnome.settings-daemon.plugins.media-keys; then
  B=org.gnome.settings-daemon.plugins.media-keys
  P=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/findnow/
  python3 - "$B" "$P" <<'PY'
import ast, subprocess, sys
schema, path = sys.argv[1], sys.argv[2]
cur = subprocess.run(["gsettings", "get", schema, "custom-keybindings"],
                     capture_output=True, text=True).stdout.strip()
paths = [p for p in ast.literal_eval(cur.replace("@as ", "")) if p != path] if cur else []
subprocess.run(["gsettings", "set", schema, "custom-keybindings", str(paths)])
PY
  gsettings reset-recursively "$B.custom-keybinding:$P" 2>/dev/null
fi
echo "✓ FindNow removed."
