# Example spectra

Real spectra for trying out pyredshift, e.g.

```
pyredshift Example-Spectra/DESI-elliptical-z0.49.fits
```

The true redshift of each object is recorded in the `Z` keyword of the
FITS table header — try to recover it before peeking!

| File | Object | z |
|------|--------|---|
| `DESI-elliptical-z0.49.fits` | Luminous red (elliptical) galaxy, DESI DR1, TARGETID 39628259121434302 (RA 18.2613°, Dec +20.0175°) | 0.4913 |

Hints for the elliptical: bin up (`b`) and look for the 4000 Å break with
the CaII K & H lines — then `ESC k` or `ESC h` on them. No emission lines
here; that's a sky residual near 9400 Å (`B` will bodge it).

Credits: DESI Data Release 1 (DESI Collaboration), retrieved via the
SPARCL service at NOIRLab's Astro Data Lab.
