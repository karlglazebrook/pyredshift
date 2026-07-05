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
    version="1.9",
    description="Interactive redshifting of 1D astronomical spectra "
                "(Python successor of pdlredshift / redshift.f)",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Karl Glazebrook",
    url="https://github.com/karlglazebrook/pyredshift",
    license="MIT",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Astronomy",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Environment :: MacOS X",
        "Environment :: X11 Applications",
    ],
    keywords="astronomy spectroscopy redshift spectra interactive",
    packages=["pyredshift"],
    package_dir={"": "src"},
    package_data={"pyredshift": ["pyredshift.lines", "pyredshift-help.html"]},
    scripts=["pyredshift"],
    install_requires=["numpy", "matplotlib", "astropy", "scipy"],
    python_requires=">=3.9",
)
