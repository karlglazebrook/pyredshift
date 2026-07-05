# Example spectra

Real spectra for trying out pyredshift, e.g.

```
pyredshift Example-Spectra/SDSS-QSO-z1.97.fits
```

The true redshift of each object is recorded in the `Z` keyword of the
FITS table header — try to recover it before peeking!

| File | Object | z |
|------|--------|---|
| `DESI-elliptical-z0.49.fits` | Luminous red (elliptical) galaxy, DESI DR1, TARGETID 39628259121434302 | 0.4913 |
| `SDSS-QSO-z1.97.fits` | Quasar, SDSS/BOSS DR17 | 1.9726 |
| `JWST-SFG-z6.96.fits` | Star-forming galaxy, JWST/NIRSpec prism (CAPERS, PID 6368) from the DAWN JWST Archive | 6.964 |

Hints:

- **Elliptical** — absorption only: bin up (`b`) and look for the 4000 Å
  break with the CaII K & H lines, then `ESC k` / `ESC h` on them. The
  spike near 9400 Å is a sky residual (`B` will bodge it).
- **QSO** — broad emission lines: `ESC c` on the strong line at ~4600 Å
  (CIV), then check CIII] and MgII line up.
- **JWST galaxy** — strong narrow lines on a faint continuum with a sharp
  Lyman-α break at ~1 µm: try `ESC O` on the strongest line ([OIII] 5007),
  then Hβ, Hα and [OII] should all click into place.

Credits: DESI Data Release 1 (DESI Collaboration) and SDSS/BOSS DR17
(SDSS Collaboration), both retrieved via the SPARCL service at NOIRLab's
Astro Data Lab; JWST/NIRSpec spectrum from the DAWN JWST Archive (DJA,
msaexp reduction v4.4), original data from the CAPERS program (PID 6368).
