#!/bin/sh
# Build FindNow's file index with plocate. No root needed; run by a systemd user timer.
#
# Indexed: your home folder, plus every drive under /mnt/* and /media/$USER/*.
# Skipped: caches, VCS/build folders, trash, and Windows system folders on dual-boot drives.
# Extra roots: list them (one per line) in ~/.config/findnow/extra-paths
set -u
OUT="${XDG_CACHE_HOME:-$HOME/.cache}/findnow"
EXTRA="${XDG_CONFIG_HOME:-$HOME/.config}/findnow/extra-paths"
mkdir -p "$OUT"

SKIP_NAMES='.git .hg .svn .idea .vs CMakeFiles node_modules __pycache__ .cache .venv venv site-packages .Trash .Trash-1000 Trash AppData $Recycle.Bin System\ Volume\ Information'
SKIP_FS='proc sysfs devpts tmpfs devtmpfs cgroup cgroup2 overlay squashfs fuse.portal fuse.gvfsd-fuse'

build() { # build <root> <db-name> [extra prune paths]
  updatedb -l no -U "$1" -o "$OUT/$2.db.tmp" --prunefs "$SKIP_FS" \
    --prunepaths "${3:-}" --prunenames "$SKIP_NAMES" \
    && mv "$OUT/$2.db.tmp" "$OUT/$2.db"
}
db_name() { printf '%s' "$1" | tr -c 'A-Za-z0-9\n' '_'; }

build "$HOME" home
WANTED="home.db"

for ROOT in /mnt/* "/media/$USER"/*; do
  [ -d "$ROOT" ] || continue
  NAME="drive$(db_name "$ROOT")"
  # Windows system folders, if this is a Windows partition
  WIN="$ROOT/Windows $ROOT/ProgramData $ROOT/Program\ Files $ROOT/Program\ Files\ (x86) $ROOT/\$WINDOWS.~BT $ROOT/\$WinREAgent $ROOT/\$Windows.~WS $ROOT/Config.Msi $ROOT/Recovery $ROOT/PerfLogs"
  build "$ROOT" "$NAME" "$WIN" && WANTED="$WANTED $NAME.db"
done

if [ -f "$EXTRA" ]; then
  while IFS= read -r ROOT; do
    case "$ROOT" in ''|'#'*) continue ;; esac
    ROOT=$(eval echo "$ROOT")  # expand ~
    [ -d "$ROOT" ] || continue
    NAME="extra$(db_name "$ROOT")"
    build "$ROOT" "$NAME" && WANTED="$WANTED $NAME.db"
  done < "$EXTRA"
fi

# drop indexes of drives that are no longer mounted
for DB in "$OUT"/*.db; do
  [ -e "$DB" ] || continue
  case " $WANTED " in *" $(basename "$DB") "*) ;; *) rm -f "$DB" ;; esac
done
