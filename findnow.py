#!/usr/bin/env python3
"""FindNow — instant file search + a deck of 8 shortcuts, one hotkey away.

Stays resident in the background and appears instantly when triggered.
Settings and shortcuts: ~/.config/findnow/shortcuts.json
File index (plocate):   ~/.cache/findnow/*.db   (rebuilt by index.sh every 15 min)

Usage:
  - Start typing             → search files; ↑↓ select, Enter open, Ctrl+Enter show in folder
  - 1–9 (empty search)       → open that tile
  - Click an empty tile      → add a folder, file, app or command
  - Right-click a tile       → rename, change target, move, remove
  - Drag a tile onto another → swap them (drop on an empty tile to move it there)
  - Esc                      → clear search / close
  - ⚙ Settings               → rows & columns, hotkey, opacity
"""
import glob
import html
import json
import os
import shlex
import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango  # noqa: E402

try:
    gi.require_version("GioUnix", "2.0")
    from gi.repository import GioUnix  # noqa: E402
    DesktopAppInfo = GioUnix.DesktopAppInfo
except (ValueError, ImportError):
    DesktopAppInfo = Gio.DesktopAppInfo

APP_ID = "io.github.findnow.FindNow"
CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "findnow")
CONFIG_FILE = os.path.join(CONFIG_DIR, "shortcuts.json")
INDEX_DIR = os.path.join(GLib.get_user_cache_dir(), "findnow")
INDEX_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.sh")
HOME = os.path.expanduser("~")
RAW_RESULTS = 4000   # candidates fetched from plocate before ranking
SHOWN_RESULTS = 60   # results listed in the UI
TILE_DRAG_PREFIX = "findnow-tile:"

DEFAULT_SETTINGS = {"opacity": 0.55, "rows": 2, "columns": 4, "hotkey": "<Control>space"}
ROWS_RANGE = (1, 6)
COLUMNS_RANGE = (1, 8)

# Hotkeys offered in Settings (any other combination can be recorded).
HOTKEY_PRESETS = [
    ("<Control>space", "Ctrl+Space"),
    ("<Super>space", "Super+Space"),
    ("<Alt>space", "Alt+Space"),
]
GNOME_KEYS_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
GNOME_BINDING_SCHEMA = GNOME_KEYS_SCHEMA + ".custom-keybinding"
GNOME_BINDING_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/findnow/"
LAUNCHER = os.path.join(HOME, ".local", "bin", "findnow")

# Fixed palette, independent of the system theme: translucent dark glass + teal accent.
CSS = """
window.findnow { background-color: transparent; }
.glass {
  background-color: rgba(12, 16, 22, %(opacity)s);
  border: 1px solid rgba(255, 255, 255, 0.10);
  border-radius: 18px;
  color: #e8eef4;
}
.hint { font-size: 11px; color: rgba(232,238,244,0.6);
        text-shadow: 0 1px 2px rgba(0,0,0,0.9); }

entry.search {
  min-height: 42px; font-size: 15px; border-radius: 12px; padding: 0 12px;
  background: rgba(255,255,255,0.07); color: #e8eef4;
  border: 1px solid rgba(255,255,255,0.14); box-shadow: none; outline: none;
}
entry.search:focus-within { border-color: #1fd1a0; box-shadow: 0 0 0 1px rgba(31,209,160,0.35); }
entry.search image { color: #1fd1a0; }
entry.search text placeholder { color: rgba(232,238,244,0.45); }

button.toolbar {
  min-width: 34px; min-height: 34px; padding: 0; border-radius: 10px;
  background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.08);
  color: #e8eef4; box-shadow: none;
}
button.toolbar:hover   { background: rgba(31, 209, 160, 0.18); border-color: rgba(31,209,160,0.6); }
button.toolbar:checked { background: rgba(31, 209, 160, 0.35); border-color: #1fd1a0; color: #ffffff; }

button.tile {
  min-width: 150px; min-height: 118px; padding: 0; border-radius: 14px;
  background: rgba(255, 255, 255, 0.07);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: #e8eef4; box-shadow: none;
  transition: background 120ms ease, border-color 120ms ease, box-shadow 120ms ease;
}
button.tile:hover, button.tile:focus-visible {
  background: rgba(31, 209, 160, 0.16);
  border-color: #1fd1a0;
  box-shadow: 0 0 0 1px rgba(31,209,160,0.35), 0 6px 18px rgba(0,0,0,0.35);
}
button.tile.empty {
  background: rgba(255,255,255,0.025);
  border: 1px dashed rgba(255,255,255,0.22);
  color: rgba(232,238,244,0.55);
}
button.tile.empty:hover { color: #1fd1a0; border-color: #1fd1a0; background: rgba(31,209,160,0.08); }
/* drop highlight must not change the border width: tiles are homogeneous, so a
   1px change would resize the whole grid (and window) while dragging */
button.tile.drop-target {
  border-color: #1fd1a0; background: rgba(31,209,160,0.25);
  box-shadow: inset 0 0 0 1px #1fd1a0, 0 0 0 1px rgba(31,209,160,0.35);
}
button.tile.dragging { opacity: 0.35; }

.tile-name { font-weight: 700; font-size: 13px; text-shadow: 0 1px 3px rgba(0,0,0,0.85); }
.badge {
  font-size: 10px; font-weight: 800; min-width: 18px; min-height: 18px;
  border-radius: 99px; padding: 0 4px;
  background: rgba(255,255,255,0.10); color: rgba(232,238,244,0.75);
}
button.tile:hover .badge, button.tile:focus-visible .badge { background: #1fd1a0; color: #0b1016; }

list.results { background: transparent; }
list.results row {
  border-radius: 10px; padding: 6px 10px; color: #e8eef4;
  background: transparent; border: 1px solid transparent;
}
list.results row:hover { background: rgba(255,255,255,0.06); }
list.results row:selected {
  background: rgba(31,209,160,0.18); border-color: rgba(31,209,160,0.55);
}
.result-name { font-weight: 600; font-size: 13px; }
.result-path { font-size: 11px; color: rgba(232,238,244,0.55); }
.status { font-size: 13px; color: rgba(232,238,244,0.55); }
scrolledwindow.results-area, scrolledwindow.results-area > viewport { background: transparent; }

popover > contents {
  background-color: rgba(16, 21, 28, 0.97); color: #e8eef4;
  border: 1px solid rgba(255,255,255,0.12); border-radius: 12px; padding: 6px;
}
popover > arrow { background-color: rgba(16, 21, 28, 0.97); border: 1px solid rgba(255,255,255,0.12); }
button.menu-item {
  background: transparent; border: none; box-shadow: none; color: #e8eef4;
  padding: 6px 10px; border-radius: 8px;
}
button.menu-item:hover { background: rgba(31,209,160,0.18); }
button.menu-item.danger { color: #ff7a7a; }
button.menu-item.danger:hover { background: rgba(255,90,90,0.15); }
.menu-title { font-size: 11px; font-weight: 700; color: rgba(232,238,244,0.5); margin: 2px 8px 4px 8px; }

window.dialog { background-color: #10151c; color: #e8eef4; }
window.dialog entry, window.dialog searchentry {
  background: rgba(255,255,255,0.06); color: #e8eef4;
  border: 1px solid rgba(255,255,255,0.14); border-radius: 8px; min-height: 34px;
}
window.dialog list { background: transparent; }
window.dialog row { border-radius: 8px; padding: 4px 6px; color: #e8eef4; }
window.dialog row:hover, window.dialog row:selected { background: rgba(31,209,160,0.18); }
button.primary {
  background: #1fd1a0; color: #0b1016; font-weight: 700; border: none;
  border-radius: 8px; padding: 6px 16px; box-shadow: none;
}
button.primary:hover { background: #3be0b2; }
.section { font-size: 11px; font-weight: 800; letter-spacing: 1.5px; color: #1fd1a0; }
.field { color: #e8eef4; }
.note { font-size: 11px; color: rgba(232,238,244,0.55); }
.note.warning { color: #ffb86b; }
window.dialog spinbutton {
  background: rgba(255,255,255,0.06); color: #e8eef4;
  border: 1px solid rgba(255,255,255,0.14); border-radius: 8px;
}
window.dialog spinbutton text { color: #e8eef4; }
window.dialog spinbutton button {
  background: transparent; color: #e8eef4; border: none; box-shadow: none;
}
window.dialog spinbutton button:hover { color: #1fd1a0; }
window.dialog dropdown > button, window.dialog button.secondary {
  background: rgba(255,255,255,0.06); color: #e8eef4; box-shadow: none;
  border: 1px solid rgba(255,255,255,0.14); border-radius: 8px; min-height: 34px;
}
window.dialog dropdown > button:hover, window.dialog button.secondary:hover {
  border-color: #1fd1a0; background: rgba(31,209,160,0.10);
}
window.dialog button.recording { border-color: #1fd1a0; color: #1fd1a0; background: rgba(31,209,160,0.14); }
popover listview { background: transparent; }
popover listview row { color: #e8eef4; border-radius: 8px; padding: 6px 8px; }
popover listview row:hover, popover listview row:selected { background: rgba(31,209,160,0.18); }
scale trough { background: rgba(255,255,255,0.15); min-height: 4px; border-radius: 4px; }
scale highlight { background: #1fd1a0; border-radius: 4px; }
scale slider { background: #e8eef4; min-width: 14px; min-height: 14px; margin: -5px; border-radius: 99px; }
"""


# ---------------------------------------------------------------- data

def default_shortcuts():
    """Sensible first-run tiles: the user's standard folders plus a few installed apps."""
    tiles = []
    for name, special in (("Desktop", GLib.UserDirectory.DIRECTORY_DESKTOP),
                          ("Downloads", GLib.UserDirectory.DIRECTORY_DOWNLOAD),
                          ("Documents", GLib.UserDirectory.DIRECTORY_DOCUMENTS)):
        path = GLib.get_user_special_dir(special)
        if path and os.path.isdir(path):
            tiles.append({"name": os.path.basename(path) or name, "path": shorten_path(path)})
    for name, candidates in (
            ("Files", ["org.gnome.Nautilus.desktop", "org.kde.dolphin.desktop",
                       "nemo.desktop", "thunar.desktop"]),
            ("Terminal", ["org.gnome.Ptyxis.desktop", "org.gnome.Console.desktop",
                          "org.gnome.Terminal.desktop", "org.kde.konsole.desktop"]),
            ("Browser", ["firefox_firefox.desktop", "firefox.desktop",
                         "google-chrome.desktop", "chromium_chromium.desktop"]),
            ("Settings", ["org.gnome.Settings.desktop", "systemsettings.desktop"])):
        for app_id in candidates:
            info = DesktopAppInfo.new(app_id)
            if info:
                tiles.append({"name": info.get_display_name() or name, "app": app_id})
                break
    return tiles[:8]


def clamp(value, low, high, default):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def load_config():
    """Return (shortcuts, settings). Tiles beyond the current grid size are kept."""
    if not os.path.exists(CONFIG_FILE):
        save_config(default_shortcuts(), dict(DEFAULT_SETTINGS))
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print(f"Could not read shortcuts.json: {e}", file=sys.stderr)
        return [{"name": "⚠ JSON error", "path": CONFIG_FILE}], dict(DEFAULT_SETTINGS)
    if isinstance(data, list):
        items, settings = data, {}
    else:
        items, settings = data.get("shortcuts", []), data.get("settings", {})
    items = [v if isinstance(v, dict) else None for v in items]
    return items, {**DEFAULT_SETTINGS, **settings}


def save_config(shortcuts, settings):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    shortcuts = list(shortcuts)
    while shortcuts and shortcuts[-1] is None:  # drop trailing empty tiles
        shortcuts.pop()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"settings": settings, "shortcuts": shortcuts}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_FILE)


def shorten_path(path):
    return "~" + path[len(HOME):] if path == HOME or path.startswith(HOME + "/") else path


def item_from_path(path):
    return {"name": os.path.basename(path.rstrip("/")) or path, "path": shorten_path(path)}


def find_icon(item):
    if item.get("icon"):
        return item["icon"]
    if item.get("app"):
        info = DesktopAppInfo.new(item["app"])
        if info and info.get_icon():
            return info.get_icon()
        return "application-x-executable"
    if item.get("path"):
        path = os.path.expanduser(item["path"])
        if os.path.isdir(path):
            return "folder"
        try:
            return Gio.File.new_for_path(path).query_info(
                "standard::icon", Gio.FileQueryInfoFlags.NONE, None).get_icon()
        except GLib.Error:
            return "text-x-generic"
    return "utilities-terminal"


def open_path(path):
    Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)


def show_in_folder(path):
    """Open the file manager on the file's folder with the file selected."""
    uri = Gio.File.new_for_path(path).get_uri()
    try:
        Gio.bus_get_sync(Gio.BusType.SESSION, None).call_sync(
            "org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
            "org.freedesktop.FileManager1", "ShowItems",
            GLib.Variant("(ass)", ([uri], "")), None, Gio.DBusCallFlags.NONE, 2000, None)
    except GLib.Error:
        open_path(os.path.dirname(path))


def launch(item):
    if item.get("app"):
        info = DesktopAppInfo.new(item["app"])
        if info is None:
            raise RuntimeError(f"App not found: {item['app']}")
        info.launch([], None)
    elif item.get("path"):
        open_path(os.path.expanduser(item["path"]))
    elif item.get("command"):
        subprocess.Popen(shlex.split(os.path.expanduser(item["command"])),
                         start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def image(icon, size):
    img = (Gtk.Image.new_from_icon_name(icon) if isinstance(icon, str)
           else Gtk.Image.new_from_gicon(icon))
    img.set_pixel_size(size)
    return img


def set_margins(widget, px):
    widget.set_margin_top(px)
    widget.set_margin_bottom(px)
    widget.set_margin_start(px)
    widget.set_margin_end(px)
    return widget


# ---------------------------------------------------------------- hotkey

def set_gnome_binding(accel):
    """Bind (or with accel='' unbind) the FindNow launcher as a GNOME custom shortcut."""
    source = Gio.SettingsSchemaSource.get_default()
    if not source or not source.lookup(GNOME_BINDING_SCHEMA, True):
        return False
    keys = Gio.Settings.new(GNOME_KEYS_SCHEMA)
    paths = list(keys.get_strv("custom-keybindings"))
    if GNOME_BINDING_PATH not in paths:
        paths.append(GNOME_BINDING_PATH)
        keys.set_strv("custom-keybindings", paths)
    binding = Gio.Settings.new_with_path(GNOME_BINDING_SCHEMA, GNOME_BINDING_PATH)
    binding.set_string("name", "FindNow")
    binding.set_string("command", LAUNCHER)
    binding.set_string("binding", accel)
    Gio.Settings.sync()
    return True


def hotkey_label(hotkey):
    for value, label in HOTKEY_PRESETS:
        if value == hotkey:
            return label
    ok, keyval, mods = Gtk.accelerator_parse(hotkey)
    return Gtk.accelerator_get_label(keyval, mods) if ok and keyval else hotkey


# ---------------------------------------------------------------- search

def index_files():
    return sorted(glob.glob(os.path.join(INDEX_DIR, "*.db")))


def _favourite_dirs():
    dirs = []
    for special in (GLib.UserDirectory.DIRECTORY_DESKTOP, GLib.UserDirectory.DIRECTORY_DOCUMENTS,
                    GLib.UserDirectory.DIRECTORY_DOWNLOAD):
        path = GLib.get_user_special_dir(special)
        if path:
            dirs.append("/" + os.path.basename(path) + "/")
    return tuple(set(dirs) | {"/Desktop/", "/Documents/", "/Downloads/"})


FAVOURITE_DIRS = _favourite_dirs()


def score(path, query, words):
    """Higher is better. Name matches, short/shallow paths and personal folders rank first."""
    name = os.path.basename(path).casefold()
    stem = os.path.splitext(name)[0]
    s = 0
    if name == query or stem == query:
        s += 120
    elif name.startswith(query):
        s += 70
    elif any(name.startswith(w) for w in words):
        s += 40
    for w in words:  # match at a word boundary: "report" → "annual_report", "Q3 Report"
        i = name.find(w)
        if i > 0 and not name[i - 1].isalnum():
            s += 15
    s -= len(name) * 0.3
    s -= path.count("/") * 2
    if "/." in path:
        s -= 45  # hidden file or folder
    if path.startswith(HOME + "/") or "/Users/" in path:
        s += 10
    if any(d in path for d in FAVOURITE_DIRS):
        s += 12
    return s


def highlight(text, words):
    """Return Pango markup with the matched parts highlighted."""
    folded = text.casefold()
    marked = [False] * len(text)
    if len(folded) == len(text):  # only when casefold kept the length
        for w in words:
            i = folded.find(w)
            while i >= 0 and w:
                for j in range(i, min(i + len(w), len(text))):
                    marked[j] = True
                i = folded.find(w, i + len(w))
    out, is_open = [], False
    for ch, m in zip(text, marked):
        if m and not is_open:
            out.append('<span foreground="#1fd1a0" weight="800">')
            is_open = True
        elif not m and is_open:
            out.append("</span>")
            is_open = False
        out.append(html.escape(ch))
    if is_open:
        out.append("</span>")
    return "".join(out)


def file_icon(path, is_dir):
    if is_dir:
        return Gio.ThemedIcon.new("folder")
    content_type, _ = Gio.content_type_guess(path, None)
    return Gio.content_type_get_icon(content_type)


# ---------------------------------------------------------------- application

class FindNow(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.start_hidden = "--background" in sys.argv
        self.shortcuts = []
        self.settings = dict(DEFAULT_SETTINGS)
        self.busy = 0            # open dialogs: don't auto-hide while > 0
        self.dragging = False    # a tile is being dragged: don't auto-hide
        self.css = Gtk.CssProvider()
        self.cancellable = None  # Gio.Cancellable of the running search
        self.results = []        # [(path, is_dir)]

    # ---- setup
    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()  # keep running while the window is hidden
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self.css, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self.shortcuts, self.settings = load_config()
        self._apply_css()
        self._build_window()
        self._apply_hotkey(self.settings.get("hotkey", DEFAULT_SETTINGS["hotkey"]))

    # ---- grid size
    @property
    def rows(self):
        return clamp(self.settings.get("rows"), *ROWS_RANGE, DEFAULT_SETTINGS["rows"])

    @property
    def columns(self):
        return clamp(self.settings.get("columns"), *COLUMNS_RANGE, DEFAULT_SETTINGS["columns"])

    @property
    def tile_count(self):
        return self.rows * self.columns

    def _apply_css(self):
        opacity = max(0.0, min(1.0, float(self.settings.get("opacity", 0.55))))
        self.css.load_from_string(CSS % {"opacity": f"{opacity:.2f}"})

    def _toolbar_button(self, icon, tooltip, cls=Gtk.Button):
        b = cls(icon_name=icon, tooltip_text=tooltip)
        b.add_css_class("toolbar")
        b.set_focus_on_click(False)
        return b

    def _build_window(self):
        w = Gtk.ApplicationWindow(application=self, title="FindNow")
        w.add_css_class("findnow")
        w.set_decorated(False)
        w.set_resizable(False)
        w.set_hide_on_close(True)

        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.root.add_css_class("glass")
        content = set_margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14), 18)

        # top bar: search + buttons
        top = Gtk.Box(spacing=6)
        self.search = Gtk.SearchEntry(placeholder_text="Search files…  (just start typing)",
                                      hexpand=True)
        self.search.add_css_class("search")
        self.search.set_search_delay(40)
        self.search.set_key_capture_widget(w)
        self.search.connect("search-changed", self._on_search_changed)
        self.search.connect("activate", lambda *_: self._open_result(in_folder=False))
        top.append(self.search)


        settings_btn = self._toolbar_button("emblem-system-symbolic",
                                            "Settings: rows & columns, hotkey, opacity")
        settings_btn.connect("clicked", lambda *_: self._open_settings())
        top.append(settings_btn)

        close = self._toolbar_button("window-close-symbolic", "Close (Esc)")
        close.connect("clicked", lambda *_: self._hide())
        top.append(close)

        # body: tiles <-> search results (same size, so the window never jumps)
        self.grid = Gtk.Grid(row_spacing=10, column_spacing=10,
                             row_homogeneous=True, column_homogeneous=True)

        self.result_list = Gtk.ListBox(activate_on_single_click=True)
        self.result_list.add_css_class("results")
        self.result_list.set_selection_mode(Gtk.SelectionMode.BROWSE)
        self.result_list.connect("row-activated", lambda _l, r: self._open_result(r.get_index()))
        self.scroller = Gtk.ScrolledWindow(child=self.result_list,
                                           hscrollbar_policy=Gtk.PolicyType.NEVER,
                                           min_content_height=250)
        self.scroller.add_css_class("results-area")
        self.status = Gtk.Label(valign=Gtk.Align.CENTER, wrap=True,
                                justify=Gtk.Justification.CENTER)
        self.status.add_css_class("status")

        self.body = Gtk.Stack(hhomogeneous=True, vhomogeneous=True,
                              transition_type=Gtk.StackTransitionType.CROSSFADE,
                              transition_duration=90)
        self.body.add_named(self.grid, "tiles")
        self.body.add_named(self.scroller, "results")
        self.body.add_named(self.status, "status")

        self.hint = Gtk.Label()
        self.hint.add_css_class("hint")
        self._hint_tiles()

        content.append(top)
        content.append(self.body)
        content.append(self.hint)
        self.root.append(content)
        w.set_child(self.root)

        # one shared popover, so it is never orphaned when tiles are rebuilt
        self.popover = Gtk.Popover(has_arrow=True)
        self.popover.set_parent(self.root)

        # CAPTURE phase: see keys before the search entry does (1–8, ↑↓, Esc)
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        w.add_controller(keys)
        w.connect("notify::is-active", self._on_focus_change)
        self.window = w

    def _hint_tiles(self):
        self.hint.set_label("type: search  ·  1–9 open  ·  empty tile: add  ·  "
                            "right-click: edit  ·  drag to reorder  ·  Esc close")

    def _hint_results(self, count):
        more = "+" if count >= SHOWN_RESULTS else ""
        self.hint.set_label(f"{count}{more} results  ·  ↑↓ select  ·  Enter open  ·  "
                            "Ctrl+Enter show in folder  ·  Esc clear")

    # ---- search
    def _on_search_changed(self, entry):
        text = entry.get_text().strip()
        if self.cancellable:
            self.cancellable.cancel()
            self.cancellable = None
        if not text:
            self.results = []
            self.body.set_visible_child_name("tiles")
            self._hint_tiles()
            return
        dbs = index_files()
        if not dbs:
            self._show_status("The file index is not ready yet.\nBuilding it now…")
            if os.path.exists(INDEX_SCRIPT):
                subprocess.Popen([INDEX_SCRIPT], start_new_session=True)
            return
        words = [w for w in text.casefold().split() if w]
        argv = ["plocate", "-d", ":".join(dbs), "-i", "-b", "-l", str(RAW_RESULTS), "--", *words]
        self.cancellable = Gio.Cancellable()
        try:
            proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE
                                      | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error as e:
            self._show_status(f"Could not start search: {e.message}")
            return
        proc.communicate_utf8_async(None, self.cancellable, self._on_search_done,
                                    (text.casefold(), words, self.cancellable))

    def _on_search_done(self, proc, result, data):
        query, words, cancellable = data
        if cancellable.is_cancelled():
            return
        try:
            _ok, stdout, _err = proc.communicate_utf8_finish(result)
        except GLib.Error:
            return
        paths = [p for p in (stdout or "").split("\n") if p]
        paths.sort(key=lambda p: score(p, query, words), reverse=True)
        self.results = [(p, os.path.isdir(p)) for p in paths[:SHOWN_RESULTS]]
        self._render_results(words)

    def _show_status(self, text):
        self.status.set_label(text)
        self.body.set_visible_child_name("status")

    def _render_results(self, words):
        self.result_list.remove_all()
        if not self.results:
            self._show_status(f"No results for “{self.search.get_text().strip()}”")
            self.hint.set_label("Esc clear")
            return
        for path, is_dir in self.results:
            row_box = Gtk.Box(spacing=12)
            row_box.append(image(file_icon(path, is_dir), 28))
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1,
                           valign=Gtk.Align.CENTER, hexpand=True)
            name = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
            name.set_markup(highlight(os.path.basename(path), words))
            name.add_css_class("result-name")
            parent = Gtk.Label(label=shorten_path(os.path.dirname(path)), xalign=0,
                               ellipsize=Pango.EllipsizeMode.MIDDLE)
            parent.add_css_class("result-path")
            text.append(name)
            text.append(parent)
            row_box.append(text)
            row = Gtk.ListBoxRow(child=row_box, tooltip_text=path)
            row.set_focusable(False)
            self.result_list.append(row)
        self.result_list.select_row(self.result_list.get_row_at_index(0))
        self.scroller.get_vadjustment().set_value(0)
        self.body.set_visible_child_name("results")
        self._hint_results(len(self.results))

    def _move_selection(self, step):
        if not self.results:
            return
        row = self.result_list.get_selected_row()
        i = (row.get_index() if row else -1) + step
        i = max(0, min(len(self.results) - 1, i))
        new = self.result_list.get_row_at_index(i)
        self.result_list.select_row(new)
        # keep the selected row visible
        ok, r = new.compute_bounds(self.result_list)
        if ok:
            adj = self.scroller.get_vadjustment()
            top, bottom = r.get_y(), r.get_y() + r.get_height()
            if top < adj.get_value():
                adj.set_value(top)
            elif bottom > adj.get_value() + adj.get_page_size():
                adj.set_value(bottom - adj.get_page_size())

    def _open_result(self, i=None, in_folder=False):
        if not self.results:
            return
        if i is None:
            row = self.result_list.get_selected_row()
            i = row.get_index() if row else 0
        path, _ = self.results[i]
        self._hide()
        try:
            show_in_folder(path) if in_folder else open_path(path)
        except GLib.Error as e:
            print(f"Could not open: {e}", file=sys.stderr)

    # ---- tiles
    def _fill_tiles(self):
        while (c := self.grid.get_first_child()) is not None:
            self.grid.remove(c)
        n, cols = self.tile_count, self.columns
        if len(self.shortcuts) < n:
            self.shortcuts += [None] * (n - len(self.shortcuts))
        for i in range(n):
            self.grid.attach(self._tile(i, self.shortcuts[i]), i % cols, i // cols, 1, 1)

    def _tile(self, i, item):
        b = Gtk.Button()
        b.add_css_class("tile")
        b.set_focus_on_click(False)  # keep focus in the search entry

        # icon + name centered; number badge on its own overlay layer so alignment holds
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                         halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        if item is None:
            b.add_css_class("empty")
            center.append(image("list-add-symbolic", 28))
            center.append(Gtk.Label(label="Add"))
            b.set_tooltip_text("Add a shortcut — or drop a file/folder here")
            b.connect("clicked", lambda *_: self._add_menu(i, b))
        else:
            center.append(image(find_icon(item), 44))
            name = Gtk.Label(label=item.get("name", "?"), ellipsize=3, max_width_chars=16,
                             justify=Gtk.Justification.CENTER)
            name.add_css_class("tile-name")
            center.append(name)
            target = item.get("path") or item.get("app") or item.get("command") or ""
            b.set_tooltip_text(f"{target}\nRight-click to edit")
            b.connect("clicked", lambda *_: self._launch(item))

        badge = Gtk.Label(label=str(i + 1), halign=Gtk.Align.START, valign=Gtk.Align.START)
        if i >= 9:
            badge.set_opacity(0.5)  # no number key beyond 9
        badge.add_css_class("badge")
        set_margins(badge, 8)

        overlay = Gtk.Overlay(child=center)
        overlay.add_overlay(badge)
        b.set_child(overlay)

        right_click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        right_click.connect("pressed", lambda *_: (self._edit_menu(i, b) if item
                                                   else self._add_menu(i, b)))
        b.add_controller(right_click)

        # drag a tile onto another one to swap them (empty tiles are drop-only)
        if item is not None:
            drag = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
            drag.connect("prepare", lambda *_: Gdk.ContentProvider.new_for_value(
                f"{TILE_DRAG_PREFIX}{i}"))

            def drag_begin(source, _drag):
                # the compositor grabs the pointer during a drag, which looks like
                # a focus loss; don't let that close the window
                self.dragging = True
                source.set_icon(Gtk.WidgetPaintable.new(b), 20, 20)
                b.add_css_class("dragging")

            def drag_end(*_):
                b.remove_css_class("dragging")
                # keep the guard briefly so the focus that returns after the drop
                # settles before auto-hide is allowed again
                GLib.timeout_add(400, self._drag_finished)
            drag.connect("drag-begin", drag_begin)
            drag.connect("drag-end", drag_end)
            b.add_controller(drag)

        # accepts tiles (to reorder) and files/folders from a file manager (to add)
        drop = Gtk.DropTarget.new(GObject.TYPE_NONE, Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        drop.set_gtypes([Gdk.FileList, GObject.TYPE_STRING])

        def drop_enter(target, _x, _y):
            b.add_css_class("drop-target")
            # a drag from inside FindNow is a tile move; anything else is a file copy
            current = target.get_current_drop()
            return (Gdk.DragAction.MOVE if current and current.get_drag()
                    else Gdk.DragAction.COPY)
        drop.connect("enter", drop_enter)
        drop.connect("leave", lambda *_: b.remove_css_class("drop-target"))
        drop.connect("drop", lambda _t, value, _x, _y: self._on_drop(i, value))
        b.add_controller(drop)
        return b

    # ---- popover menus
    def _show_popover(self, anchor, title, entries):
        """entries: [(icon, label, callback, is_dangerous)]"""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        if title:
            t = Gtk.Label(label=title.upper(), xalign=0, ellipsize=3, max_width_chars=26)
            t.add_css_class("menu-title")
            box.append(t)
        for icon, label, callback, danger in entries:
            row = Gtk.Box(spacing=10)
            row.append(image(icon, 16))
            row.append(Gtk.Label(label=label, xalign=0))
            btn = Gtk.Button(child=row)
            btn.add_css_class("menu-item")
            if danger:
                btn.add_css_class("danger")

            def clicked(_b, cb=callback):
                self.popover.popdown()
                GLib.idle_add(lambda: (cb(), False)[1])
            btn.connect("clicked", clicked)
            box.append(btn)
        self.popover.set_child(box)
        ok, r = anchor.compute_bounds(self.root)
        if ok:
            rect = Gdk.Rectangle()
            rect.x, rect.y = int(r.get_x()), int(r.get_y())
            rect.width, rect.height = int(r.get_width()), int(r.get_height())
            self.popover.set_pointing_to(rect)
        self.popover.popup()

    def _add_menu(self, i, anchor, title="Add a shortcut"):
        self._show_popover(anchor, title, [
            ("folder-symbolic", "Folder…", lambda: self._file_dialog(i, folder=True), False),
            ("text-x-generic-symbolic", "File…", lambda: self._file_dialog(i, folder=False), False),
            ("view-app-grid-symbolic", "App…", lambda: self._pick_app(i), False),
            ("utilities-terminal-symbolic", "Command…", lambda: self._enter_command(i), False),
        ])

    def _edit_menu(self, i, anchor):
        item = self.shortcuts[i]
        entries = [
            ("document-edit-symbolic", "Rename", lambda: self._rename(i), False),
            ("view-refresh-symbolic", "Change target…",
             lambda: self._add_menu(i, anchor, "New target"), False),
        ]
        if i > 0:
            entries.append(("go-previous-symbolic", "Move left", lambda: self._move(i, i - 1), False))
        if i < self.tile_count - 1:
            entries.append(("go-next-symbolic", "Move right", lambda: self._move(i, i + 1), False))
        entries.append(("user-trash-symbolic", "Remove", lambda: self._assign(i, None), True))
        self._show_popover(anchor, item.get("name", ""), entries)

    # ---- changes
    def _assign(self, i, item):
        self.shortcuts[i] = item
        self._save()
        self._fill_tiles()

    def _move(self, a, b):
        s = self.shortcuts
        s[a], s[b] = s[b], s[a]
        self._save()
        self._fill_tiles()

    def _save(self):
        try:
            save_config(self.shortcuts, self.settings)
        except OSError as e:
            print(f"Could not save: {e}", file=sys.stderr)

    def _on_drop(self, i, value):
        if isinstance(value, str):
            if not value.startswith(TILE_DRAG_PREFIX):
                return False
            try:
                source = int(value[len(TILE_DRAG_PREFIX):])
            except ValueError:
                return False
            if source != i and 0 <= source < self.tile_count:
                # defer the rebuild: the dragged tile is still mid-drag right now
                GLib.idle_add(lambda: (self._move(source, i), False)[1])
            return True
        files = [f for f in (value.get_files() if hasattr(value, "get_files") else [])
                 if f.get_path()]
        if not files:
            return False
        # extra files go to the next empty tiles
        targets = [i] + [j for j in range(self.tile_count)
                         if j != i and self.shortcuts[j] is None]
        for j, f in zip(targets, files):
            self.shortcuts[j] = item_from_path(f.get_path())
        self._save()
        self._fill_tiles()
        return True

    # ---- pickers / dialogs
    def _busy_start(self):
        self.busy += 1

    def _busy_end(self):
        self.busy = max(0, self.busy - 1)
        self.window.present()

    def _file_dialog(self, i, folder):
        d = Gtk.FileDialog(title="Choose a folder" if folder else "Choose a file", modal=True)
        d.set_initial_folder(Gio.File.new_for_path(HOME))
        self._busy_start()

        def done(dlg, result):
            try:
                f = dlg.select_folder_finish(result) if folder else dlg.open_finish(result)
            except GLib.Error:
                f = None  # cancelled
            if f and f.get_path():
                self._assign(i, item_from_path(f.get_path()))
            self._busy_end()

        (d.select_folder if folder else d.open)(self.window, None, done)

    def _dialog(self, title, width=380, height=-1):
        w = Gtk.Window(title=title, transient_for=self.window, modal=True,
                       default_width=width, default_height=height)
        w.add_css_class("dialog")
        self._busy_start()
        w.connect("close-request", lambda *_: (self._busy_end(), False)[1])
        esc = Gtk.EventControllerKey()
        esc.connect("key-pressed",
                    lambda _c, k, *_: (w.close(), True)[1] if k == Gdk.KEY_Escape else False)
        w.add_controller(esc)
        return w

    def _form(self, title, fields, on_save):
        """fields: [(label, default)] → on_save([values])"""
        w = self._dialog(title)
        box = set_margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), 16)
        entries = []
        for label, default in fields:
            l = Gtk.Label(label=label.upper(), xalign=0)
            l.add_css_class("menu-title")
            e = Gtk.Entry(text=default or "")
            box.append(l)
            box.append(e)
            entries.append(e)

        def submit(*_):
            values = [e.get_text().strip() for e in entries]
            if all(values):
                w.close()
                on_save(values)
        for e in entries:
            e.connect("activate", submit)
        btn = Gtk.Button(label="Save", halign=Gtk.Align.END, margin_top=6)
        btn.add_css_class("primary")
        btn.connect("clicked", submit)
        box.append(btn)
        w.set_child(box)
        w.present()
        entries[0].grab_focus()

    def _rename(self, i):
        item = dict(self.shortcuts[i])

        def save(values):
            item["name"] = values[0]
            self._assign(i, item)
        self._form("Rename", [("Name", item.get("name", ""))], save)

    def _enter_command(self, i):
        old = self.shortcuts[i] or {}
        self._form("Add a command",
                   [("Name", old.get("name", "")), ("Command", old.get("command", ""))],
                   lambda v: self._assign(i, {"name": v[0], "command": v[1]}))

    def _pick_app(self, i):
        w = self._dialog("Choose an app", 420, 520)
        box = set_margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), 12)
        search = Gtk.SearchEntry(placeholder_text="Search apps…")
        listbox = Gtk.ListBox(activate_on_single_click=True)
        apps = sorted((a for a in Gio.AppInfo.get_all() if a.should_show() and a.get_id()),
                      key=lambda a: a.get_display_name().casefold())
        rows = []
        for a in apps:
            row_box = Gtk.Box(spacing=10)
            row_box.append(image(a.get_icon() or "application-x-executable", 28))
            row_box.append(Gtk.Label(label=a.get_display_name(), xalign=0))
            row = Gtk.ListBoxRow(child=row_box)
            row.app = a
            listbox.append(row)
            rows.append(row)

        query = [""]

        def matches(row):
            return query[0] in row.app.get_display_name().casefold()
        listbox.set_filter_func(matches)

        def on_search(e):
            query[0] = e.get_text().casefold()
            listbox.invalidate_filter()
        search.connect("search-changed", on_search)

        def chosen(_l, row):
            a = row.app
            w.close()
            self._assign(i, {"name": a.get_display_name(), "app": a.get_id()})
        listbox.connect("row-activated", chosen)

        def on_enter(*_):  # Enter in the search box → first matching app
            for row in rows:
                if matches(row):
                    chosen(listbox, row)
                    return
        search.connect("activate", on_enter)

        box.append(search)
        box.append(Gtk.ScrolledWindow(vexpand=True, child=listbox))
        w.set_child(box)
        w.present()
        search.grab_focus()

    # ---- settings
    def _open_settings(self):
        w = self._dialog("FindNow Settings", 420)
        box = set_margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), 18)

        def section(title):
            l = Gtk.Label(label=title, xalign=0, margin_top=6)
            l.add_css_class("section")
            box.append(l)

        def row(label, widget):
            r_ = Gtk.Box(spacing=12)
            l = Gtk.Label(label=label, xalign=0, hexpand=True)
            l.add_css_class("field")
            r_.append(l)
            r_.append(widget)
            box.append(r_)

        # layout
        section("LAYOUT")
        for key, label, (low, high) in (("rows", "Rows", ROWS_RANGE),
                                        ("columns", "Columns", COLUMNS_RANGE)):
            spin = Gtk.SpinButton.new_with_range(low, high, 1)
            spin.set_value(getattr(self, key))

            def changed(sp, key=key):
                self.settings[key] = int(sp.get_value())
                self._save()
                self._fill_tiles()
            spin.connect("value-changed", changed)
            row(label, spin)
        layout_note = Gtk.Label(xalign=0, wrap=True)
        layout_note.add_css_class("note")
        layout_note.set_label("Tiles hidden by a smaller grid are kept and come back when you "
                              "make it bigger.")
        box.append(layout_note)

        # hotkey
        section("HOTKEY")
        labels = [label for _v, label in HOTKEY_PRESETS] + ["Custom…"]
        dropdown = Gtk.DropDown.new_from_strings(labels)
        record = Gtk.Button()
        record.add_css_class("secondary")
        hotkey_note = Gtk.Label(xalign=0, wrap=True)
        hotkey_note.add_css_class("note")
        state = {"recording": False, "updating": False}

        def refresh():
            current = self.settings.get("hotkey", DEFAULT_SETTINGS["hotkey"])
            values = [v for v, _l in HOTKEY_PRESETS]
            state["updating"] = True
            dropdown.set_selected(values.index(current) if current in values else len(values))
            state["updating"] = False
            record.set_label("Press a key combination…" if state["recording"]
                             else f"Record…   ({hotkey_label(current)})")
            record.remove_css_class("recording")
            if state["recording"]:
                record.add_css_class("recording")
            problem = self._hotkey_problem(current)
            hotkey_note.remove_css_class("warning")
            if problem:
                hotkey_note.add_css_class("warning")
                hotkey_note.set_label(problem)
            else:
                hotkey_note.set_label("Set as a GNOME keyboard shortcut.")

        def picked(dd, _p):
            if state["updating"]:
                return
            i = dd.get_selected()
            if i < len(HOTKEY_PRESETS):
                state["recording"] = False
                self._apply_hotkey(HOTKEY_PRESETS[i][0])
            else:
                start_recording()
            refresh()
        dropdown.connect("notify::selected", picked)

        def start_recording(*_):
            state["recording"] = True
            set_gnome_binding("")  # so the current hotkey can't fire while recording
            refresh()
        record.connect("clicked", start_recording)

        def on_key(_c, keyval, _code, mods):
            if not state["recording"]:
                return False
            if keyval == Gdk.KEY_Escape:
                state["recording"] = False
                self._apply_hotkey(self.settings.get("hotkey", DEFAULT_SETTINGS["hotkey"]))
                refresh()
                return True
            if Gdk.keyval_name(keyval) in ("Control_L", "Control_R", "Shift_L", "Shift_R",
                                          "Alt_L", "Alt_R", "Super_L", "Super_R",
                                          "Meta_L", "Meta_R", "ISO_Level3_Shift"):
                return True  # wait for the non-modifier key
            mods &= Gtk.accelerator_get_default_mod_mask()
            accel = Gtk.accelerator_name(Gdk.keyval_to_lower(keyval), mods)
            state["recording"] = False
            self._apply_hotkey(accel)
            refresh()
            return True
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", on_key)
        w.add_controller(keys)

        def closed(*_):
            if state["recording"]:  # closed mid-recording: restore the saved hotkey
                self._apply_hotkey(self.settings.get("hotkey", DEFAULT_SETTINGS["hotkey"]))
            return False
        w.connect("close-request", closed)

        row("Open FindNow with", dropdown)
        box.append(record)
        box.append(hotkey_note)

        # appearance
        section("APPEARANCE")
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.05)
        scale.set_size_request(200, -1)
        scale.set_draw_value(False)
        scale.set_value(float(self.settings.get("opacity", 0.55)))

        def opacity_changed(sc):
            self.settings["opacity"] = round(sc.get_value(), 2)
            self._apply_css()
        scale.connect("value-changed", opacity_changed)
        scale.connect("notify::has-focus", lambda *_: self._save())
        w.connect("close-request", lambda *_: (self._save(), False)[1])
        row("Background opacity", scale)

        # advanced
        section("ADVANCED")
        buttons = Gtk.Box(spacing=8, homogeneous=True)
        json_btn = Gtk.Button(label="Edit shortcuts.json")
        json_btn.add_css_class("secondary")
        json_btn.connect("clicked", lambda *_: (w.close(), self._launch({"path": CONFIG_FILE})))
        index_btn = Gtk.Button(label="Rebuild file index")
        index_btn.add_css_class("secondary")

        def rebuild(btn):
            btn.set_label("Rebuilding…")
            btn.set_sensitive(False)
            proc = Gio.Subprocess.new(["systemctl", "--user", "start", "findnow-index.service"],
                                      Gio.SubprocessFlags.STDERR_SILENCE)

            def done(p, res):
                try:
                    ok = p.wait_check_finish(res)
                except GLib.Error:
                    ok = False
                btn.set_label("Index rebuilt ✓" if ok else "Rebuild failed")
                btn.set_sensitive(True)
            try:
                proc.wait_check_async(None, done)
            except GLib.Error:
                btn.set_label("Rebuild failed")
                btn.set_sensitive(True)
        index_btn.connect("clicked", rebuild)
        buttons.append(json_btn)
        buttons.append(index_btn)
        box.append(buttons)

        w.set_child(box)
        refresh()
        w.present()

    def _hotkey_problem(self, hotkey):
        source = Gio.SettingsSchemaSource.get_default()
        if not source or not source.lookup(GNOME_BINDING_SCHEMA, True):
            return (f"Not on GNOME: bind {hotkey_label(hotkey)} to {LAUNCHER} in your "
                    "desktop's keyboard settings.")
        return None

    def _apply_hotkey(self, hotkey):
        """Save the hotkey and bind it as a GNOME custom shortcut."""
        if not hotkey:
            hotkey = DEFAULT_SETTINGS["hotkey"]
        self.settings["hotkey"] = hotkey
        self._save()
        set_gnome_binding(hotkey)

    # ---- open / hide
    def _launch(self, item):
        self._hide()
        try:
            launch(item)
        except (GLib.Error, RuntimeError, OSError) as e:
            print(f"Could not open: {e}", file=sys.stderr)

    def _hide(self):
        self.popover.popdown()
        self.window.set_visible(False)

    def _on_key(self, _c, keyval, _code, state):
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        searching = bool(self.search.get_text().strip())

        if keyval == Gdk.KEY_Escape:
            if self.popover.get_visible():
                self.popover.popdown()
            elif self.search.get_text():
                self.search.set_text("")
                self.search.grab_focus()
            else:
                self._hide()
            return True

        if searching:
            if keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
                self._move_selection(1)
                return True
            if keyval in (Gdk.KEY_Up, Gdk.KEY_KP_Up):
                self._move_selection(-1)
                return True
            if keyval in (Gdk.KEY_Page_Down, Gdk.KEY_Page_Up):
                self._move_selection(8 if keyval == Gdk.KEY_Page_Down else -8)
                return True
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                self._open_result(in_folder=ctrl)
                return True
            return False

        # empty search: 1–8 open tiles
        if not ctrl and not state & Gdk.ModifierType.ALT_MASK:
            name = Gdk.keyval_name(keyval) or ""
            digit = name[-1] if name.startswith("KP_") else name
            if len(digit) == 1 and digit.isdigit() and 1 <= int(digit) <= min(9, self.tile_count):
                i = int(digit) - 1
                item = self.shortcuts[i]
                if item:
                    self._launch(item)
                else:
                    self._add_menu(i, self.grid.get_child_at(i % self.columns,
                                                             i // self.columns))
                return True
        return False

    def _drag_finished(self):
        self.dragging = False
        if self.window.get_visible() and not self.window.is_active():
            self.window.present()
        return False

    def _can_auto_hide(self):
        w = self.window
        return (not w.is_active() and w.get_visible() and self.busy == 0
                and not self.dragging)

    def _on_focus_change(self, _w, _p):
        if self._can_auto_hide():
            # short delay: swallow transient focus loss while a dialog is opening
            GLib.timeout_add(150, lambda: (self._can_auto_hide() and self._hide(), False)[1])

    def do_activate(self):
        if self.start_hidden:
            self.start_hidden = False
            return
        if self.busy:
            self.window.present()  # a dialog is open: don't hide behind it
            return
        if self.window.get_visible():
            self._hide()  # pressing the hotkey again closes it
            return
        hotkey = self.settings.get("hotkey")
        self.shortcuts, self.settings = load_config()
        self.settings["hotkey"] = hotkey or self.settings.get("hotkey")
        self._apply_css()
        self._fill_tiles()
        self.search.set_text("")
        self.body.set_visible_child_name("tiles")
        self._hint_tiles()
        self.window.present()
        self.search.grab_focus()


if __name__ == "__main__":
    sys.exit(FindNow().run([sys.argv[0]]))
