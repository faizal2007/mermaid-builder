"""Allow ``python -m diagram_maker`` as an alternative to the console script.

The import is absolute on purpose: a frozen build (see
``scripts/build_installer.py``) runs this file as a plain script, where
``from . import main`` has no package to be relative to.
"""

from diagram_maker import main

if __name__ == "__main__":
    main()
