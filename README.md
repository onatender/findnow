# FindNow

**Instant file search and a deck of shortcuts, one hotkey away — for Linux.**

Press <kbd>Ctrl</kbd>+<kbd>Space</kbd> and FindNow is already on screen: start typing to find any file on your disks in milliseconds, or hit <kbd>1</kbd>–<kbd>8</kbd> to jump straight to the folders, files and apps you use every day. Pick a result and FindNow gets out of your way.

If you are coming from Windows and miss **Listary** or **Everything**, or from macOS and miss **Alfred** or **Spotlight**, FindNow is built for you.

<!-- Add a screenshot: docs/screenshot.png -->
<!-- ![FindNow](docs/screenshot.png) -->

## Why FindNow?

- **It's instant.** FindNow stays resident in the background with its window pre-built, so the hotkey shows it immediately, with no startup delay.
- **Search that keeps up with your typing.** Results update on every keystroke from a [plocate](https://plocate.sesse.net/) index. Queries take single-digit milliseconds, even across hundreds of thousands of files.
- **Smart ranking.** Exact name matches come first, then names that start with your query, then word-boundary matches. Files in Desktop, Documents and Downloads are boosted, and hidden files are pushed down.
- **Your favourites, one key away.** A grid of tiles (2 × 4 by default, up to 6 × 8) for the folders, files, apps or shell commands you open all the time.
- **Any hotkey.** Pick <kbd>Ctrl</kbd>+<kbd>Space</kbd>, <kbd>Super</kbd>+<kbd>Space</kbd> or <kbd>Alt</kbd>+<kbd>Space</kbd>, or record your own combination in Settings. No extra permissions needed: it's a regular GNOME shortcut.
- **Edit everything in place.** Click an empty tile to add something. Right-click a tile to rename, retarget, move or remove it. Drag tiles to reorder them, and drag files and folders straight onto a tile. You never have to touch a config file.
- **Dual-boot friendly.** Mounted drives under `/mnt` and `/media` are indexed too, and Windows system folders, `AppData` and the Recycle Bin are skipped automatically.
- **Looks good.** Translucent dark glass with a teal accent. You can adjust the opacity in Settings.
- **Small and hackable.** One Python file built on GTK4. No Electron and no daemons beyond a systemd user service.

## Install

Requirements: Ubuntu / Debian (or any distro with GTK4 + PyGObject + plocate), GNOME on Wayland or X11.

```sh
git clone https://github.com/onatender/findnow.git
cd findnow
./install.sh
```

The installer:

1. installs `python3-gi`, `gir1.2-gtk-4.0`, `libglib2.0-bin` and `plocate` with apt,
2. copies FindNow to `~/.local/share/findnow` and the launcher to `~/.local/bin/findnow`,
3. builds the file index and enables a systemd **user** timer that refreshes it every 15 minutes,
4. starts FindNow in the background on every login,
5. binds <kbd>Ctrl</kbd>+<kbd>Space</kbd> in GNOME. Any custom shortcuts you already have are left alone.

Prefer another hotkey? Set it at install time with `./install.sh --hotkey '<Super>space'`, or change it later in Settings.

Not on GNOME? Bind any key to `~/.local/bin/findnow` in your desktop's keyboard settings.

To update, `git pull` and run `./install.sh` again. To remove FindNow, run `./uninstall.sh`. Your shortcuts are kept.

## Usage

| Key / action | What it does |
|---|---|
| <kbd>Ctrl</kbd>+<kbd>Space</kbd> | Show / hide FindNow (configurable in ⚙ Settings) |
| *just type* | Search files and folders by name. Use several words to narrow it down (`q3 report`) |
| <kbd>↑</kbd> <kbd>↓</kbd> <kbd>PgUp</kbd> <kbd>PgDn</kbd> | Move through results |
| <kbd>Enter</kbd> | Open the selected result with its default app |
| <kbd>Ctrl</kbd>+<kbd>Enter</kbd> | Show the result in its folder (file manager opens with it selected) |
| <kbd>1</kbd>–<kbd>9</kbd> | Open a tile (when the search box is empty) |
| Click an empty tile | Add a **folder**, **file**, **app** or **command** |
| Right-click a tile | Rename · change target · move left/right · remove |
| Drag a tile onto another | Swap them. Drop it on an empty tile to move it there |
| Drag files in | Pin the window with 📌, then drop files from your file manager onto a tile |
| ⚙ | Settings: rows & columns, hotkey, background opacity, rebuild index |
| <kbd>Esc</kbd> | Clear the search, or close |

FindNow also closes by itself when it loses focus.

## Configuration

Everything can be done from the UI, but the files are plain text if you prefer.

**Shortcuts and settings:** `~/.config/findnow/shortcuts.json`

```json
{
  "settings": { "opacity": 0.55, "rows": 2, "columns": 4, "hotkey": "<Control>space" },
  "shortcuts": [
    { "name": "Projects", "path": "~/Projects" },
    { "name": "Budget",   "path": "~/Documents/budget.ods" },
    { "name": "Firefox",  "app": "firefox_firefox.desktop" },
    { "name": "Website",  "command": "code ~/Projects/website", "icon": "text-editor" },
    null
  ]
}
```

`hotkey` is a GTK accelerator such as `<Control>space` or `<Super>f`. Tiles beyond `rows × columns` are kept but hidden.

Each tile is one of the following. `null` leaves a tile empty.

- `path`: opens a folder or file with its default app
- `app`: launches an installed app by its `.desktop` ID
- `command`: runs a command line

Every tile also takes an optional `icon`, which is an icon-theme name.

**Extra folders to index:** by default FindNow indexes your home folder plus every drive under `/mnt/*` and `/media/$USER/*`. To add more, list them in `~/.config/findnow/extra-paths`, one per line:

```
/srv/media
/opt/projects
```

Then rebuild the index right away with `systemctl --user start findnow-index`.

**What's skipped:** `.git`, `node_modules`, `__pycache__`, `.cache`, virtualenvs, `CMakeFiles`, trash folders, and on Windows partitions `Windows`, `Program Files`, `ProgramData`, `AppData` and `$Recycle.Bin`. Edit `SKIP_NAMES` in `index.sh` to change this.

## How it works

```
Ctrl+Space ─► GNOME custom shortcut ─► ~/.local/bin/findnow
                                          │  D-Bus Activate (≈ instant)
                                          ▼
                         findnow.py  (GTK4, resident, window pre-built)
                            │                         │
                 tiles ◄────┘                         └────► plocate -i -b <words>
     ~/.config/findnow/shortcuts.json                         ~/.cache/findnow/*.db
                                                                   ▲
                                         systemd user timer ─► index.sh (every 15 min)
```

- The **launcher** is a tiny shell script that calls `org.freedesktop.Application.Activate` on the running instance, and passes along the Wayland activation token so the window gets focus. If FindNow isn't running yet, it starts it.
- **Search** runs `plocate` asynchronously on every keystroke (40 ms debounce) and cancels stale queries. It takes up to 4000 candidates, ranks them in Python and shows the top 60.
- **Indexing** uses plocate's `updatedb` in user mode (`-l no`, one database per root), so it needs no root and doesn't touch the system-wide locate database.

## Troubleshooting

- **The hotkey does nothing.** Check that the service is running with `systemctl --user status findnow`, then try `~/.local/bin/findnow` from a terminal.
- **The window shows up but doesn't get focus, or GNOME says "FindNow is ready".** This is Wayland focus-stealing prevention. Make sure the hotkey runs `~/.local/bin/findnow` through a GNOME custom shortcut, not through another tool.
- **A file you just created doesn't show up.** The index refreshes every 15 minutes. Run `systemctl --user start findnow-index` to refresh it now.
- **Logs:** `journalctl --user -u findnow -u findnow-index`

## Roadmap

- Windows version, backed by Everything's `es.exe`
- Named tabs or groups of tiles
- Content search and recently opened files

## Contributing

Issues and pull requests are welcome. The whole app is `findnow.py`, a single readable Python/GTK4 file.

## License

FindNow is free software, licensed under the [GNU General Public License v3.0](LICENSE).

---

*Keywords: Linux file search, instant search, Everything alternative for Linux, Listary alternative, Alfred / Spotlight alternative, GNOME launcher, Wayland launcher, quick launcher, file finder, plocate GUI, GTK4.*
