# Example spectra

Real spectra for trying out pyredshift, e.g.

```
pyredshift Example-Spectra/SDSS-QSO-z2.50.fits
```

The true redshift of each object is recorded in the `Z` keyword of the
FITS table header — try to recover it before peeking!

| File | Object | z |
|------|--------|---|
| `DESI-elliptical-z0.49.fits` | Luminous red (elliptical) galaxy, DESI DR1, TARGETID 39628259121434302 | 0.4913 |
| `SDSS-QSO-z2.50.fits` | Quasar, SDSS/BOSS DR17 | 2.5045 |
| `JWST-SFG-z6.96.fits` | Star-forming galaxy, JWST/NIRSpec prism (CAPERS, PID 6368) from the DAWN JWST Archive | 6.964 |

Hints:

- **Elliptical** — absorption only: bin up (`b`) and look for the 4000 Å
  break with the CaII K & H lines, then `ESC k` / `ESC h` on them. The
  spike near 9400 Å is a sky residual (`B` will bodge it).
- **QSO** — broad emission lines and the Lyα forest: `ESC l` on the
  strong peak at ~4260 Å (Lyα — note the forest absorption blueward of
  it), then check CIV, CIII] and MgII line up.
- **JWST galaxy** — strong narrow lines on a faint continuum with a sharp
  Lyman-α break at ~1 µm: try `ESC O` on the strongest line ([OIII] 5007),
  then Hβ, Hα and [OII] should all click into place.

These are real survey data — see [CREDITS.md](CREDITS.md) for full
credits and acknowledgments (DESI DR1, SDSS/BOSS DR17, SPARCL/NOIRLab,
and the DAWN JWST Archive / CAPERS).
