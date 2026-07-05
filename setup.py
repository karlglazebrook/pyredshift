from setuptools import setup

# pip install .   (from this directory)
#
# Installs:
#   the pyredshift package (redshift.py + data files pyredshift.lines,
#     pyredshift-help.html) -> site-packages/pyredshift/
#   the pyredshift script -> the bin/ of whichever python runs the install
#     (e.g. anaconda3/bin), with the shebang rewritten to that python.
#
# The package source lives in src/ (a file and a directory cannot share
# the name 'pyredshift' at the top level).

setup(
    name="pyredshift",
    version="1.5",
    description="Interactive redshifting of 1D spectra "
                "(Python successor of pdlredshift / redshift.f)",
    author="Karl Glazebrook",
    packages=["pyredshift"],
    package_dir={"": "src"},
    package_data={"pyredshift": ["pyredshift.lines", "pyredshift-help.html"]},
    scripts=["pyredshift"],
    install_requires=["numpy", "matplotlib", "astropy", "scipy"],
    python_requires=">=3.9",
)
