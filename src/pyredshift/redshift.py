"""
pyredshift.redshift

Module containing the Python version of Karl's redshift browsing program.
Port of KGB::Redshift v2.0 (Perl/PDL/PGPLOT) to numpy/matplotlib.

Keeps the synchronous PGPLOT-style interaction: a blocking pgband() reads
the cursor + one key, and a single main loop dispatches on the key.
Style is deliberately plain and procedural, like the Perl original.

V1.0 - Initial port from Redshift.pm v2.0, Jul 2026.
     - NaN is used for bad values throughout; matplotlib breaks the
       plotted line at NaNs so the old hand-drawn pgbin() is not needed.
     - 'p' prints to PDF (pyredshift.pdf) instead of EPS.
V1.1 - White background is now the default; dark=1 gives the PGPLOT look.
     - New pyredshift.lines format: CSV with unicode labels and
       matplotlib colour names (see the header of that file).
     - Tightened the margins around the axes.
V1.2 - Toolbar integration: pan/zoom/Home/Back/Forward now update the view
       state properly; Home returns to the startup view.
     - 'h' = home, '?' = help.
     - Left-button drag = rubber-band zoom (like 'e'); a purely
       horizontal drag zooms X only, purely vertical Y only.
V1.3 - '?' opens the help in its own window.
     - Window size is remembered between runs (~/.pyredshift.json) and
       clamped to the screen if the display has changed.
V1.4 - Help is now pyredshift-help.html, opened themed in the browser
       (falls back to a plain-text window); '?' button on the canvas
       (the native Mac toolbar cannot take custom buttons).
V1.5 - Renamed: the module is now pyredshift.redshift (the kg namespace
       is retired for distribution).
V1.6 - Continuous cursor readout (pixel, wavelength obs/rest, flux) at
       the bottom right of the window; EW/flux measurements are also
       shown in the window message area.
V1.7 - Works from a Jupyter notebook: redshift(wave, flux) pops up the
       interactive window outside the notebook (inline backends cannot
       deliver events), and on quit the final view is embedded in the
       cell and the original backend restored.  Cleanup is guaranteed
       even on Kernel->Interrupt, and headless/remote kernels are
       detected up front (clear error instead of a Qt kernel crash).
V1.8 - Right-click pops up the quick line list as a menu: pick a line
       to set the redshift at the clicked position (same as ESC+key).
"""

import ctypes
import json
import os
import sys
import time
import warnings
from html.parser import HTMLParser

import numpy as np
import matplotlib

# Pick a GUI backend unless the user forced one via MPLBACKEND
if "MPLBACKEND" not in os.environ:
    for _backend in ("QtAgg", "MacOSX", "TkAgg"):
        try:
            matplotlib.use(_backend)
            break
        except ImportError:
            continue

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.transforms import Bbox
from matplotlib.widgets import Button, Cursor

# Take all the keys back from matplotlib's default bindings (k, l, s, g, o, q...)
for _p in [p for p in plt.rcParams if p.startswith("keymap.")]:
    plt.rcParams[_p] = []

# Spectra are full of NaNs and zero continua - don't spam warnings about it
np.seterr(divide="ignore", invalid="ignore")
warnings.filterwarnings("ignore", message="Mean of empty slice")
try:
    warnings.simplefilter("ignore", np.RankWarning)
except AttributeError:
    pass

__version__ = "1.8"

C_LIGHT = 2.99792458e8  # m/s

TEMPLATE_NAME = "GNIRS_N4608"  # template for the 't' key

CONFIG_FILE = os.path.expanduser("~/.pyredshift.json")  # remembers window size
DEFAULT_FIGSIZE = (13.0, 5.5)  # inches

# Colours are named for the white (default) background; on a dark background
# some need brightening for legibility - this remaps them.
DARK_REMAP = {"gold": "yellow", "tab:blue": "dodgerblue", "green": "lime",
              "darkblue": "dodgerblue", "seagreen": "greenyellow",
              "black": "white", "darkorange": "orange"}


def theme_col(c, light):
    return c if light else DARK_REMAP.get(c, c)

# Quick line guess shortcuts (rest wavelengths in Angstroms)
shortcuts = {"l": 1216, "c": 1549, "m": 2800, "o": 3727, "k": 3933, "h": 3969,
             "g": 4304, "b": 4861, "O": 5007, "d": 5892, "a": 6563}

def load_help_html():
    """The command help lives in pyredshift-help.html next to the module.
    Placeholders ({template}, {linelist}) are filled in by help_html()."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "pyredshift-help.html")
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return None


class _HelpText(HTMLParser):
    """Crude HTML -> text, for the terminal echo and the no-browser
    fallback window.  Table rows become multi-space separated columns."""

    def __init__(self):
        super().__init__()
        self.out = []
        self.table = None  # rows of the current table
        self.row = None    # cells of the current table row
        self.cell = None   # accumulating text of the current cell/heading

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table = []
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th", "h1", "h2", "p"):
            self.cell = ""

    def handle_endtag(self, tag):
        if tag == "table" and self.table:
            # Emit the whole table with aligned columns
            ncol = max(len(r) for r in self.table)
            rows = [r + [""] * (ncol - len(r)) for r in self.table]
            widths = [max(len(r[i]) for r in rows) for i in range(ncol)]
            self.out.append("")
            for r in rows:
                line = "    " + "   ".join(c.ljust(w) for c, w in zip(r, widths))
                self.out.append(line.rstrip())
            self.table = None
        elif tag == "tr" and self.table is not None:
            self.table.append(self.row)
            self.row = None
        elif self.cell is not None and tag in ("td", "th", "h1", "h2", "p"):
            # (inline tags like <code> inside a cell just pass through)
            text = " ".join(self.cell.split())  # normalise whitespace
            if tag in ("td", "th") and self.row is not None:
                self.row.append(text)
            elif tag in ("h1", "h2"):
                self.out.extend(["", "  " + text.upper()])
            elif tag == "p":
                self.out.extend(["", "  " + text])
            self.cell = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data

    def text(self):
        return "\n".join(self.out) + "\n"


def plain_help(raw):
    if raw is None:
        return "Help file (pyredshift-help.html) not found next to the module\n"
    parser = _HelpText()
    parser.feed(raw)
    return parser.text()


HELP_RAW = load_help_html()


def linelist_html():
    """Auto-generated table of the line list for the help page, two
    column-pairs wide, each line coloured as plotted."""
    if line_wav is None:
        load_linelist()
    light = not dark_mode
    cells = []
    for i in range(len(line_wav)):
        if line_label[i] == "IGNORE" or line_wav[i] <= 0:
            continue  # killed with 'k' this session
        wav = line_wav[i] * (10000.0 if micron_mode else 1.0)
        col = theme_col(line_col[i], light)
        cells.append("<td>%.2f</td><td><span style='color:%s'>&#9632;</span> "
                     "%s</td>" % (wav, col, line_label[i]))
    half = (len(cells) + 1) // 2
    rows = ["<tr><th>&lambda; vac</th><th>Line</th>"
            "<th>&lambda; vac</th><th>Line</th></tr>"]
    for i in range(half):
        right = cells[i + half] if i + half < len(cells) else "<td></td><td></td>"
        rows.append("<tr>%s%s</tr>" % (cells[i], right))
    return "<table class='linelist'>\n%s\n</table>" % "\n".join(rows)


def help_html():
    """The help HTML body with the placeholders filled in."""
    if HELP_RAW is None:
        return None
    return HELP_RAW.format(template=TEMPLATE_NAME, linelist=linelist_html())


# ---------------------------------------------------------------------------
# Module state - plain globals, in the spirit of the Perl original
# ---------------------------------------------------------------------------
fig = None
ax = None
cursor = None
message_artist = None

w = None            # wavelength array
f = None            # flux array
specgood = None     # boolean mask of good (finite) pixels
anybad = False
label = ""
dark_mode = 0       # 1 = PGPLOT-style black background
zshift = 0.0        # the redshift ($redshift in Perl; renamed to avoid the sub name clash)
found = 0
micron_mode = 0
unit = "Angstroms"
med = 0.0
xstart = xend = ylo = yhi = 0.0

line_wav = None
line_col = None
line_name = []
line_label = []

got_cuum = 0
f_cuum = None
RMS = 0.0
got_bin = 0
w_bin = f_bin = None
bin_off = 0.0
got_smooth = 0
f_smooth = None
smooth_off = 0.0
plot_template = 0
w_temp = f_temp = None
norm = 1.0


# ---------------------------------------------------------------------------
# Cursor and blocking input - the pgband() replacement
# ---------------------------------------------------------------------------
class StickyCursor(Cursor):
    """Cursor that survives full canvas repaints and toolbar pan/zoom.

    A blitted Cursor is erased by any full redraw and only reappears on the
    next mouse move; remember the last motion event and re-draw the crosshair
    after every repaint.  Also reimplements onmove() without the base class's
    widgetlock check, so the crosshair stays live while the toolbar pan/zoom
    mode is switched on.
    """

    def __init__(self, ax_, **kwargs):
        self._last_event = None
        super().__init__(ax_, **kwargs)
        self.connect_event("draw_event", self._redraw)

    def onmove(self, event):
        # Copy of Cursor.onmove from matplotlib 3.9, minus the widgetlock
        # check (version sensitive - revisit if matplotlib is upgraded)
        if self.ignore(event):
            return
        if not self.ax.contains(event)[0]:
            self._last_event = None  # or _redraw() would resurrect it
            self.linev.set_visible(False)
            self.lineh.set_visible(False)
            if self.needclear:
                self.canvas.draw()
                self.needclear = False
            return
        self._last_event = event
        self.needclear = True
        xdata, ydata = self._get_data_coords(event)
        self.linev.set_xdata((xdata, xdata))
        self.linev.set_visible(self.visible and self.vertOn)
        self.lineh.set_ydata((ydata, ydata))
        self.lineh.set_visible(self.visible and self.horizOn)
        if not (self.visible and (self.vertOn or self.horizOn)):
            return
        # Redraw
        if self.useblit:
            if self.background is not None:
                self.canvas.restore_region(self.background)
            self.ax.draw_artist(self.linev)
            self.ax.draw_artist(self.lineh)
            self.canvas.blit(self.ax.bbox)
        else:
            self.canvas.draw_idle()

    def _redraw(self, event):
        if self._last_event is not None:
            self.onmove(self._last_event)


def normkey(ch):
    # Some backends report shifted letters as 'shift+b' - normalise to 'B'
    if ch is not None and ch.startswith("shift+") and len(ch) == 7:
        return ch[-1].upper()
    return ch


def pgband(allow_drag=False):
    """Block until a key press or mouse click; return (x, y, ch) in data coords.

    Mouse button gives ch='A', as PGPLOT did. Returns ch='q' if the window
    is closed.

    With allow_drag=True a left-button drag rubber-band zooms (like 'e') and
    returns ch='drag' after updating the view state; a purely horizontal drag
    zooms X only, a purely vertical one Y only.  Short drags (<5 pixels)
    still count as a click.
    """
    if fig is None or not plt.fignum_exists(fig.number):
        return None, None, "q"
    result = {}
    drag = {}

    def done(x, y, ch):
        result["x"], result["y"], result["ch"] = x, y, ch
        fig.canvas.stop_event_loop()

    def toolbar_mode():
        toolbar = getattr(fig.canvas.manager, "toolbar", None)
        return getattr(toolbar, "mode", "") if toolbar is not None else ""

    def on_key(ev):
        done(ev.xdata, ev.ydata, normkey(ev.key))

    def on_press(ev):
        if ev.inaxes is not ax:
            return  # clicks elsewhere (margins, the ? button) aren't cursor reads
        if allow_drag and ev.button == 3:
            done(ev.xdata, ev.ydata, "menu")  # right-click: quick line menu
            return
        if allow_drag and ev.button == 1 and not toolbar_mode():
            drag["xpx"], drag["ypx"] = ev.x, ev.y     # pixels, for threshold
            drag["x0"], drag["y0"] = ev.xdata, ev.ydata
            drag["x1"], drag["y1"] = ev.xdata, ev.ydata
            drag["rect"] = ax.add_patch(Rectangle(
                (ev.xdata, ev.ydata), 0, 0, fill=False,
                edgecolor="red", lw=0.8, ls="--"))
        else:
            done(ev.xdata, ev.ydata, "A")

    def on_motion(ev):
        if "rect" not in drag or ev.inaxes is not ax:
            return
        drag["x1"], drag["y1"] = ev.xdata, ev.ydata
        drag["rect"].set_bounds(drag["x0"], drag["y0"],
                                ev.xdata - drag["x0"], ev.ydata - drag["y0"])
        fig.canvas.draw_idle()

    def on_release(ev):
        global xstart, xend, ylo, yhi
        if "rect" not in drag:
            return
        drag.pop("rect").remove()
        fig.canvas.draw_idle()
        xmoved = abs(ev.x - drag["xpx"]) > 5
        ymoved = abs(ev.y - drag["ypx"]) > 5
        if not (xmoved or ymoved):  # just a click
            done(drag["x0"], drag["y0"], "A")
            return
        if xmoved:
            xstart, xend = sorted((drag["x0"], drag["x1"]))
        if ymoved:
            ylo, yhi = sorted((drag["y0"], drag["y1"]))
        done(drag["x1"], drag["y1"], "drag")

    def on_close(ev):
        done(None, None, "q")

    cids = [fig.canvas.mpl_connect("key_press_event", on_key),
            fig.canvas.mpl_connect("button_press_event", on_press),
            fig.canvas.mpl_connect("motion_notify_event", on_motion),
            fig.canvas.mpl_connect("button_release_event", on_release),
            fig.canvas.mpl_connect("close_event", on_close)]
    fig.canvas.start_event_loop()
    for cid in cids:
        fig.canvas.mpl_disconnect(cid)
    rect = drag.get("rect")
    if rect is not None and rect.axes is not None:
        rect.remove()  # a key press ended the loop mid-drag
    return result.get("x"), result.get("y"), result.get("ch")


def refresh():
    fig.canvas.draw_idle()
    fig.canvas.flush_events()


# ---------------------------------------------------------------------------
# Right-click quick-line menu - the ESC shortcut list as a popup, drawn
# with matplotlib artists so it works on any backend
# ---------------------------------------------------------------------------
def line_menu(xd, yd):
    """Pop up the quick line list at the cursor (right-click).  Returns
    the chosen rest wavelength (in current wavelength units), or None if
    cancelled (click elsewhere, or any key)."""
    # Entries from the ESC shortcut list, labelled from the line list,
    # padded into aligned columns (monospace)
    entries = []
    for key, wav in sorted(shortcuts.items(), key=lambda kv: kv[1]):
        wrest = wav / 10000.0 if micron_mode else float(wav)
        i = int(np.argmin(np.abs(line_wav - wrest)))
        lab = line_label[i] if line_label[i] != "IGNORE" else str(wav)
        wav_A = line_wav[i] * (10000.0 if micron_mode else 1.0)  # true vacuum
        entries.append(("%-7s %4.0f" % (lab, wav_A), wrest))
    n = len(entries)

    # Geometry from real font metrics (hardcoded pixels break on HiDPI)
    fs = 10
    probe = fig.text(0.5, 0.5, max(e[0] for e in entries),
                     fontsize=fs, family="monospace")
    try:
        bb = probe.get_window_extent()
    except Exception:
        fig.canvas.draw()
        bb = probe.get_window_extent()
    probe.remove()
    ih = bb.height * 1.55       # row height
    pad = bb.height * 0.55      # box padding
    tpad = bb.height * 0.7      # text indent
    wpx = bb.width + 2 * tpad
    hpx = n * ih + 2 * pad

    # Anchor at the click, kept on-canvas
    x0, y0 = ax.transData.transform((xd, yd))
    if x0 + wpx > fig.bbox.width:
        x0 -= wpx
    top = min(max(y0, hpx), fig.bbox.height)

    inv = fig.transFigure.inverted()
    fx0, fbot = inv.transform((x0, top - hpx))
    fx1, ftop = inv.transform((x0 + wpx, top))
    light = not dark_mode
    box = Rectangle((fx0, fbot), fx1 - fx0, ftop - fbot,
                    transform=fig.transFigure, zorder=50, lw=1,
                    facecolor="#fffdf2" if light else "#222222",
                    edgecolor="black" if light else "#aaaaaa")
    fig.add_artist(box)
    hi = Rectangle((fx0, fbot), fx1 - fx0, 0, transform=fig.transFigure,
                   facecolor="#378ADD", alpha=0.35, zorder=51, visible=False)
    fig.add_artist(hi)
    texts = []
    for k, (labtext, wrest) in enumerate(entries):
        tx, ty = inv.transform((x0 + tpad, top - pad - k * ih - 0.74 * ih))
        texts.append(fig.text(tx, ty, labtext, fontsize=fs, zorder=52,
                              family="monospace",
                              color="black" if light else "white"))
    if cursor is not None:
        cursor.active = False  # freeze the crosshair on the anchor point
    refresh()

    def index_at(ev):
        if ev.x is None or not (x0 <= ev.x <= x0 + wpx):
            return None
        k = int((top - pad - ev.y) // ih)
        return k if (0 <= k < n and top - pad - n * ih <= ev.y <= top - pad) \
            else None

    state = {"k": None, "picked": None}

    def on_move(ev):
        k = index_at(ev)
        if k != state["k"]:
            state["k"] = k
            if k is None:
                hi.set_visible(False)
            else:
                _, hy0 = inv.transform((0, top - pad - (k + 1) * ih))
                _, hy1 = inv.transform((0, top - pad - k * ih))
                hi.set_bounds(fx0, hy0, fx1 - fx0, hy1 - hy0)
                hi.set_visible(True)
            fig.canvas.draw_idle()

    def on_click(ev):
        state["picked"] = index_at(ev)
        fig.canvas.stop_event_loop()

    def on_key(ev):
        state["picked"] = None
        fig.canvas.stop_event_loop()

    cids = [fig.canvas.mpl_connect("motion_notify_event", on_move),
            fig.canvas.mpl_connect("button_press_event", on_click),
            fig.canvas.mpl_connect("key_press_event", on_key)]
    fig.canvas.start_event_loop()
    for cid in cids:
        fig.canvas.mpl_disconnect(cid)
    box.remove()
    hi.remove()
    for t in texts:
        t.remove()
    if cursor is not None:
        cursor.active = True
    refresh()
    return entries[state["picked"]][1] if state["picked"] is not None else None


# ---------------------------------------------------------------------------
# Continuous cursor readout - bottom right corner of the window.
# The text is an animated artist blitted over a snapshot of its corner of
# the figure, so tracking the mouse costs two cheap blits per move, not a
# full redraw (same trick as the crosshair).
# ---------------------------------------------------------------------------
readout_artist = None
readout_bg = None      # (background, bbox) pair for blitting
readout_lastev = None  # last motion event, to survive full redraws


def make_readout():
    global readout_artist, readout_bg, readout_lastev
    readout_artist = fig.text(0.995, 0.012, "", ha="right", va="bottom",
                              family="monospace", fontsize=8, animated=True,
                              color="white" if dark_mode else "black")
    readout_bg = None
    readout_lastev = None
    fig.canvas.mpl_connect("draw_event", snapshot_readout)
    fig.canvas.mpl_connect("motion_notify_event", update_readout)


def snapshot_readout(ev):
    """Cache the bottom-right corner after every full draw (the readout
    artist is animated, so it is never part of the cached image), then
    re-render the readout so redraws don't blank it - recomputed, so a
    new redshift updates the rest wavelength immediately."""
    global readout_bg
    W, H = fig.bbox.width, fig.bbox.height
    box = Bbox([[0.40 * W, 0.0], [W, 0.055 * H]])
    readout_bg = (fig.canvas.copy_from_bbox(box), box)
    if readout_lastev is not None:
        update_readout(readout_lastev)


def update_readout(ev):
    global readout_lastev
    if readout_artist is None or readout_bg is None or f is None:
        return
    readout_lastev = ev
    if ev.inaxes is ax and ev.xdata is not None:
        i = int(np.argmin(np.abs(w - ev.xdata)))
        wfmt = "%.5f" if micron_mode else "%.2f"
        rest = wfmt % (ev.xdata / (1 + zshift)) if found else "-"
        text = ("pix %d   y %.4g   λ %s   rest %s   flux %.4g"
                % (i, ev.ydata, wfmt % ev.xdata, rest, f[i]))
    else:
        text = ""
    readout_artist.set_text(text)
    bg, box = readout_bg
    fig.canvas.restore_region(bg)
    fig.draw_artist(readout_artist)
    fig.canvas.blit(box)


# ---------------------------------------------------------------------------
# Simulated terminal in the plot window - port of pgwin_prompt/pgwin_message
# ("Ghastly but works and is convenient")
# ---------------------------------------------------------------------------
def win_message(text):
    global message_artist
    if message_artist is not None:
        try:
            message_artist.remove()
        except ValueError:
            pass
        message_artist = None
    if text and text.strip():
        message_artist = fig.text(0.06, 0.02, text, color="red", fontsize=9)
    refresh()


def get_input_win(prompt, default):
    """Prompt in the plot window; typed keys echo there. Enter accepts,
    empty input returns the default (FIGARO style)."""
    win_message("")
    prompt_art = fig.text(0.06, 0.045, "%s [%s]: " % (prompt, default),
                          color="red", fontsize=9)
    typed_art = fig.text(0.06, 0.012, "", fontsize=9,
                         color=theme_col("green", not dark_mode))
    refresh()
    s = ""
    while True:
        if not plt.fignum_exists(fig.number):
            break
        _, _, ch = pgband()
        if ch is None or ch == "A":
            continue
        if ch == "enter":
            break
        if ch == "backspace":
            s = s[:-1]
        elif len(ch) == 1:
            s += ch
        else:
            continue  # ignore modifier keys etc
        typed_art.set_text(s)
        refresh()
    try:
        prompt_art.remove()
        typed_art.remove()
    except ValueError:
        pass
    refresh()
    return str(default) if s.strip() == "" else s


def get_number_win(prompt, default):
    s = get_input_win(prompt, default)
    try:
        return float(s)
    except ValueError:
        print("Could not parse '%s', using %s" % (s, default))
        win_message("Could not parse '%s', using %s" % (s, default))
        return float(default)


def nint(x):
    return int(np.floor(x + 0.5))


# ---------------------------------------------------------------------------
# Jupyter / IPython support - the interactive window opens OUTSIDE the
# notebook (inline backends cannot deliver mouse/key events to a blocking
# loop), and the final view is embedded in the cell on quit.
# ---------------------------------------------------------------------------
GUI_BACKENDS = ("macosx", "qtagg", "qt5agg", "tkagg",
                "gtk3agg", "gtk4agg", "wxagg")


def in_ipython():
    try:
        from IPython import get_ipython
        return get_ipython() is not None
    except ImportError:
        return False


def in_notebook():
    """True in a Jupyter kernel (as opposed to terminal IPython)."""
    try:
        from IPython import get_ipython
        ip = get_ipython()
        return ip is not None and type(ip).__name__ == "ZMQInteractiveShell"
    except ImportError:
        return False


def display_available():
    """Can a GUI window exist here?  Remote/headless kernels (JupyterHub,
    ssh without X forwarding) cannot - and on Linux, Qt may hard-abort
    the kernel rather than fail politely, so check first."""
    if sys.platform == "darwin" or sys.platform.startswith("win"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def ensure_gui_backend():
    """Under IPython with a non-interactive backend (inline, ipympl, Agg)
    switch to a native GUI backend so the window can pop up.  Returns the
    previous backend name if we switched (restored on quit), else None."""
    if not in_ipython():
        return None
    # Respect an explicitly forced backend - but NOT the inline/ipympl one,
    # because ipykernel itself sets MPLBACKEND to that in every notebook
    forced = os.environ.get("MPLBACKEND", "")
    if forced and "inline" not in forced and "ipympl" not in forced:
        return None
    current = matplotlib.get_backend()
    if current.lower() in GUI_BACKENDS:
        return None
    if not display_available():
        raise RuntimeError(
            "pyredshift opens its interactive window on the machine where "
            "the kernel runs, but this kernel appears to be headless or "
            "remote (no DISPLAY). Run it with a local kernel, or with X "
            "forwarding.")
    for cand in ("MacOSX", "QtAgg", "TkAgg"):
        try:
            plt.switch_backend(cand)
        except Exception:
            continue
        print("Opening the interactive window outside the notebook "
              "(backend %s -> %s); press q there to return." % (current, cand))
        return current
    print("WARNING: backend %s is not interactive and no GUI backend could "
          "be loaded - the window will not respond." % current)
    return None


def final_view_png():
    """Render the current view to PNG bytes, independent of the live
    backend (used to embed the final plot in the notebook cell)."""
    import io
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    pfig = Figure(figsize=fig.get_size_inches())
    FigureCanvasAgg(pfig)
    pax = pfig.add_subplot()
    set_margins(pfig)
    render(pax)
    buf = io.BytesIO()
    pfig.savefig(buf, format="png", dpi=110, facecolor=pfig.get_facecolor())
    return buf.getvalue()


def show_in_cell(png):
    try:
        from IPython.display import display, Image
    except ImportError:
        return
    display(Image(png))


# ---------------------------------------------------------------------------
# Config file - remembers the window size between runs
# ---------------------------------------------------------------------------
def load_config():
    try:
        with open(CONFIG_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_config(**kw):
    cfg = load_config()
    cfg.update(kw)
    try:
        with open(CONFIG_FILE, "w") as fh:
            json.dump(cfg, fh, indent=1)
    except OSError as err:
        print("Could not save %s: %s" % (CONFIG_FILE, err))


def screen_size_px():
    """Best-effort main screen size in pixels, or None if it cannot be found.

    On the Mac ask CoreGraphics directly via ctypes - do NOT use tkinter
    here: a Tk/macOS version mismatch aborts the whole process uncatchably.
    """
    if sys.platform == "darwin":
        try:
            cg = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
            cg.CGMainDisplayID.restype = ctypes.c_uint32
            cg.CGDisplayPixelsWide.restype = ctypes.c_size_t
            cg.CGDisplayPixelsWide.argtypes = [ctypes.c_uint32]
            cg.CGDisplayPixelsHigh.restype = ctypes.c_size_t
            cg.CGDisplayPixelsHigh.argtypes = [ctypes.c_uint32]
            display = cg.CGMainDisplayID()
            return (int(cg.CGDisplayPixelsWide(display)),
                    int(cg.CGDisplayPixelsHigh(display)))
        except Exception:
            return None
    try:  # elsewhere a throwaway Tk root works fine
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        size = (root.winfo_screenwidth(), root.winfo_screenheight())
        root.destroy()
        return size
    except Exception:
        return None


def startup_figsize():
    """The last run's window size (inches), clamped to the current screen
    so a move to a smaller display degrades gracefully.  Clamping is a
    uniform scaling, so the aspect ratio is always preserved - unless the
    saved aspect is daft (>10:1 either way), which we assume is user error
    and replace with the default shape."""
    figsize = load_config().get("figsize", list(DEFAULT_FIGSIZE))
    try:
        figsize = [float(figsize[0]), float(figsize[1])]
        aspect = figsize[0] / figsize[1]
        if aspect > 10.0 + 1e-9 or aspect < 0.1 - 1e-9:  # beyond 10:1 = stupid
            figsize = list(DEFAULT_FIGSIZE)
    except (TypeError, ValueError, IndexError, ZeroDivisionError):
        figsize = list(DEFAULT_FIGSIZE)
    # Tiny-size floor (catches corrupt configs), aspect-preserving
    scale = max(1.0, 3.0 / figsize[0], 2.0 / figsize[1])
    figsize = [figsize[0] * scale, figsize[1] * scale]
    # Fit to the screen LAST (leaving room for the menubar) with ONE scale
    # factor, so the aspect ratio survives and the window always fits
    screen = screen_size_px()
    if screen:
        dpi = matplotlib.rcParams["figure.dpi"]
        scale = min(1.0, 0.95 * screen[0] / dpi / figsize[0],
                    0.88 * screen[1] / dpi / figsize[1])
        figsize = [figsize[0] * scale, figsize[1] * scale]
    return figsize


# ---------------------------------------------------------------------------
# Help ('?' key or the corner button) - themed HTML in the browser,
# else a plain-text matplotlib window
# ---------------------------------------------------------------------------
help_fig = None
help_button = None


def place_help_button():
    """Keep the '?' button a constant physical size in the top-right
    corner, whatever the window size."""
    w, h = fig.get_size_inches()
    bw, bh, pad = 0.30 / w, 0.26 / h, 0.05
    help_button.ax.set_position([1 - bw - pad / w, 1 - bh - pad / h, bw, bh])


def make_help_button():
    """A '?' help button on the canvas (the native Mac toolbar cannot
    take custom buttons)."""
    global help_button
    if dark_mode:
        face, hover, fg = "#333333", "#555555", "white"
    else:
        face, hover, fg = "#e8e8e8", "#d0d0d0", "black"
    help_button = Button(fig.add_axes([0.95, 0.95, 0.04, 0.04]), "?",
                         color=face, hovercolor=hover)
    help_button.label.set_color(fg)
    help_button.label.set_fontweight("bold")
    help_button.on_clicked(lambda event: show_help())
    place_help_button()

HELP_CSS = """
body { font-family: -apple-system, "Helvetica Neue", sans-serif;
       max-width: 46em; margin: 2em auto; padding: 0 1em;
       color: %(fg)s; background: %(bg)s; line-height: 1.45; }
h1 { font-size: 1.5em; border-bottom: 2px solid %(rule)s; padding-bottom: 0.2em; }
h2 { font-size: 1.15em; color: %(accent)s; margin-top: 1.4em; }
table { border-collapse: collapse; margin: 0.5em 0; }
th, td { border: 1px solid %(rule)s; padding: 0.25em 0.7em; text-align: left; }
th { background: %(thbg)s; }
td:first-child, td:nth-child(3) {
     font-family: ui-monospace, Menlo, monospace; font-weight: bold;
     white-space: nowrap; }
table.linelist td:first-child, table.linelist td:nth-child(3) {
     font-weight: normal; }
code { font-family: ui-monospace, Menlo, monospace; background: %(thbg)s;
       padding: 0 0.25em; border-radius: 3px; }
/* CSS-only tabs (radio button trick) */
input[name="tabs"] { display: none; }
nav.tabs { border-bottom: 2px solid %(rule)s; margin-top: 1em; }
nav.tabs label { display: inline-block; padding: 0.35em 1.3em; cursor: pointer;
     border: 1px solid %(rule)s; border-bottom: none; margin: 0 0.3em -2px 0;
     border-radius: 7px 7px 0 0; background: %(thbg)s; }
section.tab { display: none; }
#tab-keys:checked ~ #pane-keys, #tab-lines:checked ~ #pane-lines,
#tab-guide:checked ~ #pane-guide
     { display: block; }
#tab-keys:checked ~ nav label[for="tab-keys"],
#tab-lines:checked ~ nav label[for="tab-lines"],
#tab-guide:checked ~ nav label[for="tab-guide"]
     { background: %(bg)s; border-bottom: 2px solid %(bg)s; font-weight: bold; }
"""


def show_help_browser(body):
    """Write the themed help page and open it in the default browser.
    Returns False if that isn't possible."""
    if body is None:
        return False
    import webbrowser
    colours = ({"fg": "#ddd", "bg": "#111", "rule": "#555",
                "accent": "#f66", "thbg": "#222"} if dark_mode else
               {"fg": "#111", "bg": "#fff", "rule": "#bbb",
                "accent": "crimson", "thbg": "#f0f0f0"})
    html = ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<title>pyredshift help</title><style>%s</style></head>"
            "<body>%s</body></html>" % (HELP_CSS % colours, body))
    path = os.path.expanduser("~/.pyredshift-help.html")
    try:
        with open(path, "w") as fh:
            fh.write(html)
        return webbrowser.open("file://" + path)
    except OSError:
        return False


def show_help():
    global help_fig
    body = help_html()
    text = plain_help(body)
    print(text)
    if show_help_browser(body):
        return
    if help_fig is not None and plt.fignum_exists(help_fig.number):
        try:
            help_fig.canvas.manager.show()  # raise the existing window
        except Exception:
            pass
        return
    # Size the window to the help text
    nlines = text.count("\n") + 1
    help_fig = plt.figure(figsize=(6.6, min(0.19 * nlines + 0.4, 10.0)))
    try:
        help_fig.canvas.manager.set_window_title("pyredshift help")
    except AttributeError:
        pass
    fg = "white" if dark_mode else "black"
    help_fig.set_facecolor("black" if dark_mode else "white")
    help_fig.text(0.05, 0.98, text,
                  family="monospace", fontsize=9, va="top", color=fg)
    try:
        help_fig.show()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Line list
# ---------------------------------------------------------------------------
def load_linelist():
    global line_wav, line_col
    line_name.clear()
    line_label.clear()
    module_dir = os.path.dirname(os.path.abspath(__file__))
    lines_file = os.path.join(module_dir, "pyredshift.lines")
    # lines_file = "/Users/karl/Dropbox/Templates/LineLists/Ivo-LRD-lines.dat"  ## KG change temp
    print("Reading line list (vacuum wavelengths) from", lines_file)
    if not os.path.exists(lines_file):
        raise FileNotFoundError("Lines file not found at %s" % lines_file)
    # CSV format: wavelength_Angstroms, name, label, colour, comment
    # label defaults to name, colour to red; the comment is ignored
    wavs = []
    line_col = []
    with open(lines_file) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            t = [s.strip() for s in line.split(",")]
            name = t[1] if len(t) > 1 else ""
            lab = t[2] if len(t) > 2 and t[2] else name
            col = t[3] if len(t) > 3 and t[3] else "red"
            wavs.append(float(t[0]))
            line_name.append(name)
            line_label.append(lab)
            line_col.append(col)
    line_wav = np.array(wavs)


# ---------------------------------------------------------------------------
# Template spectra - port of KGB::SpecUtils::get_template's search path
# ---------------------------------------------------------------------------
def get_template(name):
    """Read a template spectrum from the well-known locations
    (env DATADIR is at top of search path)."""
    candidates = [name]
    dirs = []
    if os.environ.get("DATADIR"):
        dirs.append(os.environ["DATADIR"])
    if os.environ.get("NEWMODELS"):
        dirs.append(os.path.join(os.environ["NEWMODELS"], "Spectra"))
    if os.environ.get("HOME"):
        dirs.append(os.path.join(os.environ["HOME"], "Templates", "Spectra"))
    for d in dirs:
        candidates.append(os.path.join(d, name))
        candidates.append(os.path.join(d, name + ".dat"))
    for full in candidates:
        if os.path.exists(full):
            print("Opening file %s..." % full)
            wt, ft = np.loadtxt(full, usecols=(0, 1), comments="#", unpack=True)
            return wt, ft
    raise FileNotFoundError("Unable to locate template %s" % name)


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------
def draw_labels(ax_, printing=False):
    light = printing or not dark_mode
    for i in range(len(line_wav)):
        if line_label[i] == "IGNORE":
            continue
        col = theme_col(line_col[i], light)
        wline = line_wav[i] * (1 + zshift)
        yvalue = yhi - yhi * 0.08 + ((i + 1) % 2) * yhi * 0.03
        if xstart <= wline <= xend:
            ls = "--" if printing else "-"
            ax_.text(wline, yvalue, line_label[i], color=col,
                     ha="center", fontsize=8)
            ax_.plot(wline, yvalue - yhi * 0.02, marker=7, color=col, ms=4)
            ax_.plot([wline, wline], [yhi - yhi * 0.1, ylo],
                     color=col, lw=0.7, ls=ls)


MARGINS = dict(left=0.65, right=0.15, top=0.35, bottom=0.85)  # inches


def set_margins(fig_):
    """Fixed physical margins around the axes (room for labels and the
    in-window prompt lines) whatever the window size - fractional margins
    waste acres of space on a big monitor."""
    w, h = fig_.get_size_inches()
    fig_.subplots_adjust(left=MARGINS["left"] / w,
                         right=1 - MARGINS["right"] / w,
                         top=1 - MARGINS["top"] / h,
                         bottom=MARGINS["bottom"] / h)


def render(ax_, printing=False):
    """Draw the whole plot onto ax_ - used for both screen and 'p' printing."""
    light = printing or not dark_mode
    fg = "black" if light else "white"
    bg = "white" if light else "black"
    lab_col = "crimson"
    spec_col = theme_col("tab:blue", light)  # C0, the matplotlib default blue
    bin_col = theme_col("seagreen", light)
    smooth_col = "magenta"
    cuum_col = theme_col("darkorange", light)

    ax_.clear()
    ax_.figure.set_facecolor(bg)
    ax_.set_facecolor(bg)
    for spine in ax_.spines.values():
        spine.set_color(fg)
    ax_.tick_params(colors=fg, direction="in", top=True, right=True)
    ax_.set_xlim(xstart, xend)
    ax_.set_ylim(ylo, yhi)
    ax_.set_xlabel("Wavelength / %s" % unit, color=lab_col)
    ax_.set_ylabel("Flux", color=lab_col)
    ax_.set_title(label, color=lab_col, fontsize=9)
    ax_.axhline(0, color=fg, lw=0.6)

    # Don't plot the raw spectrum if a zero-offset binned/smoothed one replaces it
    if not ((got_bin and bin_off == 0) or (got_smooth and smooth_off == 0)):
        ax_.plot(w, f, drawstyle="steps-mid", color=spec_col, lw=0.7)
    if got_cuum:
        ax_.plot(w, f_cuum, color=cuum_col, lw=1.0)
    if got_bin:
        ax_.plot(w_bin, f_bin + bin_off, drawstyle="steps-mid", color=bin_col, lw=0.9)
    if got_smooth:
        ax_.plot(w, f_smooth + smooth_off, drawstyle="steps-mid",
                 color=smooth_col, lw=0.9)
    if found:
        draw_labels(ax_, printing)
        ax_.text(0.0, 1.01, "z = %-10.4f" % zshift, transform=ax_.transAxes,
                 va="bottom", color=fg, fontsize=12)
    if plot_template:
        ax_.plot(w_temp * (1 + zshift), f_temp * norm, color="red", lw=0.8)
    # Little marker along the bottom showing where the bad values are
    if anybad:
        ax_.plot(w, ylo + (~specgood) * (yhi - ylo) / 30.0, color="orange", lw=0.7)


def sync_limits(ax_):
    """Fold toolbar pan/zoom changes back into our view state, so the next
    keyboard redraw keeps the view (and draws the line labels) there."""
    global xstart, xend, ylo, yhi
    xstart, xend = ax_.get_xlim()
    ylo, yhi = ax_.get_ylim()
    # Toolbar Home/Back/Forward arrive with no drag mode active - give those
    # a full redraw so the line labels follow immediately.  (During pan/zoom
    # drags this fires on every mouse move, so just track the numbers there.)
    toolbar = getattr(fig.canvas.manager, "toolbar", None)
    if toolbar is not None and not getattr(toolbar, "mode", ""):
        draw_plot()


def draw_plot():
    global cursor
    if cursor is not None:
        cursor.disconnect_events()  # its artists die with ax.clear()
        cursor = None
    render(ax, printing=False)
    # Connect AFTER render so our own set_xlim/set_ylim don't fire it;
    # ax.clear() wipes these callbacks so reconnect on every redraw
    ax.callbacks.connect("xlim_changed", sync_limits)
    ax.callbacks.connect("ylim_changed", sync_limits)
    cursor = StickyCursor(ax, useblit=True, color="red", lw=0.8)
    refresh()


# ---------------------------------------------------------------------------
# The main event: redshift($wav, $flux, $redshift, $label) -> z
# ---------------------------------------------------------------------------
final_png = None  # final view for the notebook cell, set on 'q'


def redshift(w_in, f_in, zz=None, label_in="", dark=0):
    """Do the redshift thing - if zz is defined this is the first guess.
    dark=1 gives a PGPLOT-style black background. Returns the final redshift.

    This wrapper guarantees cleanup - window teardown and (in a notebook)
    backend restore - however the session ends: 'q', window close,
    Kernel->Interrupt, or an error."""
    global final_png
    final_png = None
    prev_backend = ensure_gui_backend()
    try:
        return _redshift_session(w_in, f_in, zz, label_in, dark)
    finally:
        try:
            if help_fig is not None and plt.fignum_exists(help_fig.number):
                plt.close(help_fig)
        except Exception:
            pass
        try:
            if fig is not None and plt.fignum_exists(fig.number):
                plt.close(fig)
                # plt.close only SCHEDULES the window teardown - pump the
                # GUI event loop briefly so it actually happens; nobody
                # pumps it after we return (else a Qt window lingers,
                # beachballing)
                for _ in range(20):
                    fig.canvas.flush_events()
                    time.sleep(0.01)
        except Exception:
            pass
        if prev_backend is not None:
            try:
                plt.switch_backend(prev_backend)
            except Exception:
                pass
        if final_png is not None:
            show_in_cell(final_png)


def _redshift_session(w_in, f_in, zz, label_in, dark):
    global fig, ax, cursor, message_artist, dark_mode, final_png
    global w, f, specgood, anybad, label, zshift, found
    global micron_mode, unit, med, xstart, xend, ylo, yhi
    global line_wav, line_col
    global got_cuum, f_cuum, RMS, got_bin, w_bin, f_bin, bin_off
    global got_smooth, f_smooth, smooth_off, plot_template, w_temp, f_temp, norm

    w = np.asarray(w_in, float).copy()
    f = np.asarray(f_in, float).copy()
    label = label_in
    dark_mode = dark

    specgood = np.isfinite(f)
    anybad = not specgood.all()
    if anybad:
        print("BAD values detected, will handle.")

    got_cuum = got_bin = got_smooth = plot_template = 0
    f_cuum = None
    RMS = 0.0
    bin_off = smooth_off = 0.0
    binfac = 3
    fwhm = 3
    fluxtype = 0  # data units for 'm', asked once on first use
    zoomx = zoomy = 2.0

    if zz is None or zz == "":
        zshift = 0.0
        found = 0
    else:
        zshift = float(zz)
        found = 1

    micron_mode = 1 if np.nanmax(w) < 100 else 0  # use microns for IR spectra
    unit = "μm" if micron_mode else "Angstroms"

    load_linelist()
    if micron_mode:
        line_wav = line_wav / 10000.0

    # Clever autoscaling
    xstart = float(np.nanmin(w))
    xend = float(np.nanmax(w))
    med = float(np.nanmedian(f[specgood])) if specgood.any() else 0.0
    # Handle some NIR spectra with lots of zeroes which causes median=0
    if med == 0:
        nz = f[specgood]
        nz = nz[nz != 0.0]
        if nz.size:
            med = float(np.nanmedian(nz))
    ylo = -3 * med
    yhi = 10 * med

    fig, ax = plt.subplots(figsize=startup_figsize())
    try:
        fig.canvas.manager.set_window_title("pyredshift")
    except AttributeError:
        pass
    set_margins(fig)
    make_help_button()
    make_readout()

    def on_resize(ev):
        set_margins(fig)
        place_help_button()

    fig.canvas.mpl_connect("resize_event", on_resize)

    home_range = (xstart, xend, ylo, yhi)  # 'h' and toolbar Home restore this

    plt.show(block=False)
    draw_plot()

    # Seed the toolbar's view history with the startup view: this enables the
    # Home button from the start, and makes it return all the way to this
    # view (not just to wherever the first pan/zoom happened to begin)
    toolbar = getattr(fig.canvas.manager, "toolbar", None)
    if toolbar is not None:
        toolbar.push_current()

    redraw = 0
    while True:  # Main loop

        if redraw:
            draw_plot()
            redraw = 0

        xv, yv, ch = pgband(allow_drag=True)
        if ch is None:
            continue

        # Main character key block

        if ch == "q":
            # Remember the window size for next time
            save_config(figsize=[float(v) for v in fig.get_size_inches()])
            # Leave a static image of the final view in the notebook cell
            # (the wrapper's cleanup displays it after the window is gone)
            if in_notebook():
                final_png = final_view_png()
            return zshift

        elif ch == "h":
            print("Restoring initial display range...")
            xstart, xend, ylo, yhi = home_range
            redraw = 1

        elif ch == "?":
            show_help()

        # Keys below need a cursor position inside the axes
        elif xv is None and ch not in ("d", "w", "=", "r", "p", "b", "s", "t", "_"):
            win_message("Cursor is outside the plot axes")

        ############### Pan/zoom stuff ###############

        elif ch == "i":
            print("Zooming along Y axis...")
            dy = abs(yhi - ylo) / zoomy
            ylo = yv - dy / 2.0
            yhi = yv + dy / 2.0
            redraw = 1
        elif ch == "o":
            print("Unzooming along Y axis...")
            dy = abs(yhi - ylo) * zoomy
            ylo = yv - dy / 2.0
            yhi = yv + dy / 2.0
            redraw = 1
        elif ch == "z":
            print("Zooming along X axis...")
            dx = abs(xend - xstart) / zoomx
            xstart = xv - dx / 2.0
            xend = xv + dx / 2.0
            redraw = 1
        elif ch == "u":
            print("Unzooming along X axis...")
            dx = abs(xend - xstart) * zoomx
            xstart = xv - dx / 2.0
            xend = xv + dx / 2.0
            redraw = 1
        elif ch == "x":
            win_message("Move cursor to other end of X range and press any key...")
            newx, newy, ch2 = pgband()
            win_message("")
            if newx is not None:
                xstart, xend = sorted((xv, newx))
            redraw = 1
        elif ch == "y":
            win_message("Move cursor to other end of Y range and press any key...")
            newx, newy, ch2 = pgband()
            win_message("")
            if newy is not None:
                ylo, yhi = sorted((yv, newy))
            redraw = 1
        elif ch == "e":
            win_message("Move cursor to other end of region and press any key...")
            newx, newy, ch2 = pgband()
            win_message("")
            if newx is not None:
                xstart, xend = sorted((xv, newx))
                ylo, yhi = sorted((yv, newy))
            redraw = 1
        elif ch == "drag":  # rubber-band zoom; pgband already set the range
            print("Zooming to selected region...")
            redraw = 1
        elif ch == "[":
            print("Panning left...")
            dx = abs(xend - xstart)
            xstart -= 0.7 * dx
            xend -= 0.7 * dx
            redraw = 1
        elif ch == "]":
            print("Panning right...")
            dx = abs(xend - xstart)
            xstart += 0.7 * dx
            xend += 0.7 * dx
            redraw = 1
        elif ch == "a":
            print("Autoscaling Y axis...")
            ylo = -0.5 * med
            yhi = 3 * med
            redraw = 1
        elif ch == "w":
            print("Setting whole X range...")
            xstart = float(np.nanmin(w))
            xend = float(np.nanmax(w))
            redraw = 1
        elif ch == "d":
            print("Redrawing plot...")
            redraw = 1
            got_cuum = got_bin = got_smooth = 0

        ### Cuum fitting and EW measurement ###

        elif ch == "_":
            mask = np.zeros(f.size)
            while True:
                win_message("Fit: define LHS of continuum...(Q to exit)")
                xv1, _, ch1 = pgband()
                if ch1 in ("q", "Q") or xv1 is None:
                    break
                win_message("Fit: define RHS of continuum...(Q to exit)")
                xv2, _, ch2 = pgband()
                if ch2 in ("q", "Q") or xv2 is None:
                    break
                if xv1 > xv2:
                    xv1, xv2 = xv2, xv1
                ix = (w >= xv1) & (w <= xv2)
                ax.plot(w[ix], f[ix], drawstyle="steps-mid", lw=0.8,
                        color=theme_col("darkorange", not dark_mode))
                refresh()
                mask[ix] = 1
            win_message(" ")
            if mask.sum() > 0.1:
                while True:
                    order = nint(get_number_win("Order of continuum fit?", 1))
                    # Note slightly different to redshift.f as uses 3 not 2 sigma
                    mask2 = mask.copy()
                    mask2[~specgood] = 0
                    for _ in range(10):  # Iterate
                        good = mask2 > 0
                        if good.sum() < order + 2:
                            win_message("Too few pixels left for the fit!")
                            break
                        coef = np.polyfit(w[good], f[good], order)
                        f_cuum = np.polyval(coef, w)
                        resid = np.where(good, f - f_cuum, 0.0)
                        RMS = float(np.sqrt((mask2 * resid**2).sum() / mask2.sum()))
                        dev = np.abs(np.where(specgood, f - f_cuum, 0.0))
                        mask2[dev > 3 * RMS] = 0
                    pc = 100 * (1 - mask2.sum() / mask.sum())
                    print("3 sigma clipped RMS = %g with %.1f %% of pixels rejected"
                          % (RMS, pc))
                    ax.plot(w, f_cuum, lw=1.0,
                            color=theme_col("darkorange", not dark_mode))
                    refresh()
                    ok = get_input_win(
                        "RMS = %.4g, %.0f%% clipped - fit acceptable?"
                        % (RMS, pc), "yes")
                    if ok.strip().lower().startswith("y"):
                        break
                got_cuum = 1
            else:
                win_message("No continuum defined")

        elif ch == "m":  # EW
            if f_cuum is None:
                win_message("Need to define continuum first")
                continue
            xv1 = xv
            ewcol = theme_col("green", not dark_mode)
            ax.plot([xv1, xv1], [ylo, yhi], color=ewcol, lw=0.8)
            refresh()
            win_message("Now define other side of line...")
            xv2, _, ch2 = pgband()
            win_message(" ")
            if xv2 is None:
                continue
            ax.plot([xv2, xv2], [ylo, yhi], color=ewcol, lw=0.8)
            refresh()
            if xv1 > xv2:
                xv1, xv2 = xv2, xv1
            dw = np.roll(w, -1) - w
            dw[-1] = 0
            idx = (w >= xv1) & (w <= xv2) & specgood & np.isfinite(f_cuum)
            # Only ask for the data units once per session
            while fluxtype < 1 or fluxtype > 3:
                fluxtype = int(get_number_win(
                    "Are the data units (1) Counts (2) Flambda /A or (3) Fnu /Hz ?", 2))
            df = RMS  # Fake (constant) error

            EW = float(((1 - f[idx] / f_cuum[idx]) * dw[idx]).sum()) / (1 + zshift)
            dEW = float(np.sqrt(((df / f_cuum[idx])**2 * dw[idx]**2).sum())) / (1 + zshift)

            if fluxtype == 1:
                lineflux = float((f[idx] - f_cuum[idx]).sum())
                dlineflux = float(np.sqrt((df**2 * np.ones(idx.sum())).sum()))
            elif fluxtype == 2:
                lineflux = float(((f[idx] - f_cuum[idx]) * dw[idx]).sum())
                dlineflux = float(np.sqrt(((df * dw[idx])**2).sum()))
            else:
                sf = 1e6 if micron_mode else 1e10  # c in wavelength units per second
                dnu = C_LIGHT * sf * dw[idx] / w[idx]**2
                lineflux = float(((f[idx] - f_cuum[idx]) * dnu).sum())
                dlineflux = float(np.sqrt(((df * dnu)**2).sum()))

            print("Measured Rest EW = %g +- %g" % (EW, dEW))
            print("Measured Flux = %g +- %g" % (lineflux, dlineflux))
            print("Wavelength range %g to %g" % (xv1, xv2))
            win_message("Rest EW = %.4g ± %.3g    Line flux = %.4g ± %.3g    "
                        "(%.6g–%.6g %s)"
                        % (EW, dEW, lineflux, dlineflux, xv1, xv2, unit))

        ############### Redshift guessing ###############

        elif ch == "g":
            print("Guessing line at current position...")
            wavelength = get_number_win("Rest wavelength of line",
                                        "%.2f" % (xv / (1 + zshift)))
            i = int(np.argmin(np.abs(wavelength - line_wav)))  # Find nearest line
            zshift = xv / line_wav[i] - 1
            print("Redshift = %10.4f" % zshift)
            found = 1
            redraw = 1

        elif ch in ("escape", "`"):
            win_message("Enter shortcut key for line at position...")
            xv, yv, ch2 = pgband()
            win_message("")
            if xv is None:
                continue
            if ch2 in ("escape", "`"):
                wavelength = xv / (1.0 + zshift)  # Refine redshift
            elif ch2 in shortcuts:
                wavelength = shortcuts[ch2] / (10000.0 if micron_mode else 1.0)
            else:
                win_message("No shortcut for key '%s'" % ch2)
                continue
            i = int(np.argmin(np.abs(wavelength - line_wav)))  # Find nearest line
            zshift = xv / line_wav[i] - 1
            print("Redshift = %10.4f" % zshift)
            found = 1
            redraw = 1

        elif ch == "menu":  # right-click: pick a line from the quick list
            picked = line_menu(xv, yv)
            if picked is not None:
                i = int(np.argmin(np.abs(picked - line_wav)))
                zshift = xv / line_wav[i] - 1
                print("Redshift = %10.4f" % zshift)
                found = 1
                redraw = 1

        elif ch == "=":
            zshift = get_number_win("Enter redshift", zshift)
            found = 1
            redraw = 1

        elif ch == "r":
            print("Removing features from plot")
            found = 0
            redraw = 1

        ############### Other stuff ###############

        elif ch == "b":
            binfac = nint(get_number_win("Enter binning factor", binfac))
            if binfac > 1:
                bin_off = get_number_win("Enter Yoffset for plot", bin_off)
                npix = f.size // binfac
                # Clever code to rebin using reshape and mean! (nanmean handles bad)
                f_bin = np.nanmean(f[:npix * binfac].reshape(npix, binfac), axis=1)
                w_bin = np.nanmean(w[:npix * binfac].reshape(npix, binfac), axis=1)
                got_bin = 1
            redraw = 1

        elif ch == "s":
            fwhm = nint(get_number_win("Enter FWHM factor (pixels)", fwhm))
            if fwhm > 0:
                smooth_off = get_number_win("Enter Yoffset for plot", smooth_off)
                # Gaussian kernel with 3*FWHM width
                sig = fwhm / (2 * np.sqrt(2 * np.log(2)))
                klen = max(nint(3 * fwhm), 1)
                rv = np.abs(np.arange(klen) - (klen - 1) / 2.0)
                kern = np.exp(-0.5 * (rv / sig)**2)
                kern /= kern.sum()
                # Smooth with bad handling
                from scipy.ndimage import convolve1d
                f2 = np.where(specgood, f, 0.0)
                f_smooth = convolve1d(f2, kern, mode="reflect")
                # Norm of masked smooth, = 1 if all pixels good, <1 otherwise
                n = convolve1d(specgood.astype(float), kern, mode="reflect")
                f_smooth = f_smooth / n
                f_smooth[n < 0.5] = np.nan  # require half of kernel for valid smooth
                got_smooth = 1
            redraw = 1

        elif ch in (" ", "A"):
            i = int(np.argmin(np.abs(w - xv)))  # Find nearest pixel in wavelength
            print("XY= (%8.2f, %10g)  Pixel = %d   Flux = %10g Rest = %8.2f"
                  % (xv, yv, i, f[i], w[i] / (1 + zshift)))

        elif ch == "k":
            ii = int(np.argmin(np.abs(line_wav - xv / (1 + zshift))))
            line_label[ii] = "IGNORE"
            line_wav[ii] = -1  # Kill line
            print("Redrawing plot...")
            redraw = 1
            got_cuum = got_bin = got_smooth = 0

        elif ch == "B":
            win_message("Move cursor to other end of X range and press any key...")
            newx, newy, ch2 = pgband()
            win_message("")
            if newx is None:
                continue
            x1, x2 = sorted((xv, newx))
            f[(w > x1) & (w < x2)] = 0
            redraw = 1

        elif ch == "p":
            outfile = "pyredshift.pdf"
            pfig, pax = plt.subplots(figsize=(10.5, 5.25))
            set_margins(pfig)
            render(pax, printing=True)
            pfig.savefig(outfile, facecolor="white")
            plt.close(pfig)
            print("Printed plot to %s" % outfile)
            win_message("Printed plot to %s" % outfile)

        elif ch == "t":  # Read a template and plot it quickly for comparison
            print("Plotting %s template..." % TEMPLATE_NAME)
            try:
                w_temp, f_temp = get_template(TEMPLATE_NAME)
            except FileNotFoundError as err:
                print(err)
                win_message(str(err))
                continue
            # Highly empirical robust normalisation scheme!
            # first define middle third of the displayed wavelength range
            x1 = 0.5 * (xstart + xend) - (xend - xstart) / 3
            x2 = 0.5 * (xstart + xend) + (xend - xstart) / 3
            # Now normalise using median to avoid outliers
            sel = f[(w > x1) & (w < x2)]
            wt = w_temp * (1 + zshift)
            selt = f_temp[(wt > x1) & (wt < x2)]
            if sel.size == 0 or selt.size == 0:
                win_message("Template does not overlap the displayed wavelength range")
                continue
            norm = float(np.nanmedian(sel)) / float(np.nanmedian(selt))
            plot_template = 1
            redraw = 1

        # End of char key block
    # End main loop
