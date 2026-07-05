# CLAUDE.md — pyredshift

Interactive redshifting of 1D spectra, by eye. Python descendant of
`redshift.f` (FIGARO/Fortran, Durham 1992) via `pdlredshift` (Perl/PDL/
PGPLOT). The originals live untracked in this folder (`pdlredshift`,
`Redshift.pm`) and at `~/Dropbox/Software/figaro/redshift.f` — consult
them for intended behaviour; feature parity with the Perl version was
the porting contract.

## Code style — non-negotiable

Plain procedural "easy to read Perl style" python. Module-level globals
for state (declared in one `global` block per function), simple
functions, a single blocking main loop with if/elif key dispatch.
**Avoid OO and callbacks/delegates** except where matplotlib forces it
(widget subclasses, event handlers) — and then keep them thin. Keep the
dated version-history entries in the module docstring (a tradition
running since 1992) and add one per release. Comments in Karl's voice;
preserve original comment text when refactoring.

## Layout

```
pyredshift               script: CLI + all the spectrum-format readers
                         (deliberately in the script, NOT the module)
src/pyredshift/          the package (src layout: a file and a dir
  redshift.py            cannot both be called "pyredshift")
  pyredshift.lines       line list: CSV, VACUUM wavelengths, colour may
                         be "light/dark" pair; ships with the module
  pyredshift-help.html   help source ({template}/{linelist} placeholders)
```

The script prepends `<script-dir>/src` and `<cwd>/src` to sys.path, so
a dev checkout always runs its own package. Data files are read from
the module's own directory and MUST ship together (`package_data`).

## Architecture of redshift.py

- `redshift()` is a thin wrapper: Jupyter backend switch up front, the
  session inside `try`, guaranteed cleanup in `finally` (close windows,
  pump GUI events, restore backend, embed final PNG in the notebook
  cell). `_redshift_session()` is the whole tool and knows nothing
  about notebooks.
- `pgband(allow_drag=False)` is the PGPLOT-style blocking primitive:
  returns (x, y, key); mouse click = 'A', right-click = 'menu' and
  left-drag = rubber-band zoom (main loop only, via allow_drag=True).
- Blitting pattern (used by StickyCursor crosshair and the bottom-right
  readout): animated artist + background snapshot on draw_event +
  re-render after every full draw, else the artist vanishes on redraws.
- `draw_plot()` recreates the cursor and axes callbacks every time —
  `ax.clear()` (inside `render()`) destroys both.
- Theme: white default; `--retro`/`dark=1` for the PGPLOT black look.
  All colours resolve through `theme_col(spec, light)`; spec may be a
  single name (DARK_REMAP brightens for dark) or "light/dark".
- In-window prompts (`get_input_win`/`win_message`) draw text under the
  axes — the third-generation descendant of the "ugly hack stolen from
  2dFGRS runz" (2003). Keep it.
- Margins are fixed physical inches (`MARGINS`/`set_margins`), never
  figure fractions. Window geometry persists in ~/.pyredshift.json
  (aspect-preserving screen clamp; aspect beyond 10:1 = user error).
- Popup geometry (line_menu, help button, readout) must derive from
  measured font metrics or physical inches — hardcoded pixels break on
  HiDPI/retina (bitten twice).

## Hard-won gotchas

- **Never create a tkinter root on this Mac** — Tk version mismatch
  aborts the process uncatchably. Screen size comes from CoreGraphics
  via ctypes (`screen_size_px`).
- **ipykernel exports MPLBACKEND=…inline in every notebook** — respect
  an explicit MPLBACKEND only when it is NOT inline/ipympl.
- **`plt.close()` only schedules Qt window teardown** — pump
  `canvas.flush_events()` afterwards or the window beachballs.
- **Stale `build/` dirs bake old files into wheels** — `rm -rf build
  *.egg-info src/*.egg-info` around installs.
- StickyCursor.onmove is a copy of matplotlib 3.9's Cursor.onmove minus
  the widgetlock check — re-sync if matplotlib is upgraded.
- matplotlib's default keymaps steal the command keys — cleared at
  import.
- Notebook use needs a local kernel (window opens on the kernel's
  display); `display_available()` pre-flights this.

## Testing (headless)

No committed test suite; test scripts are written ad hoc (session
scratchpad). Pattern: `MPLBACKEND=Agg`, monkeypatch `pgband` /
`get_input_win` / `win_message` / `show_help_browser` to script a whole
session; fire synthetic `MouseEvent`/`KeyEvent` through
`canvas.callbacks.process(...)` (swap `canvas.start_event_loop` for a
feeder function to test menus/gestures); a fake Jupyter shell needs an
`.events.register` attribute. Reader tests build tiny synthetic FITS
files with astropy covering each format branch. Always re-run a full
scripted-session regression after touching the main loop.

## Workflows

- Dev run: `./pyredshift Example-Spectra/...fits` in this folder.
- Install/refresh: `/opt/anaconda3/bin/pip install --force-reinstall
  --no-deps .` (Karl's live python is /opt/anaconda3, has PyQt →
  QtAgg in notebooks, MacOSX backend otherwise).
- Branches: `main` = releases, `experimental` = risky features; merge
  to main when proven, then fast-forward experimental to match.
- Release: bump `__version__` (redshift.py) AND `version=` (setup.py)
  AND add the docstring history entry; commit; `git tag -a vX.Y`;
  `gh release create vX.Y`. Update README/help when keys change —
  help lives in pyredshift-help.html (Commands/Line list/Guide tabs).
- Example spectra are real survey data — update
  `Example-Spectra/CREDITS.md` when adding any.

## Saved for later (unimplemented redshift.f keys)

`l` list lines, `n` add line, `f` zoom factors, `j` tag line with "?",
`M` fixed-45Å EW box, `v` RMS in region, `c` insert comment,
`-`/`+`/`@` multispectral (fibre survey) navigation.
