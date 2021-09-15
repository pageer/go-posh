#!/usr/bin/env python
# Copyright (c) 2002-2008 ActiveState Software
# Author: Trent Mick (trentm@gmail.com)

"""Quick directory changing (super-cd)

'go' is a simple command line script to simplify jumping between
directories in the shell. You can create shortcut names for commonly
used directories and invoke 'go <shortcut>' to switch to that directory
-- among other little features.
"""

import os
import sys
from distutils.core import setup

if sys.version_info < (3, 0):
    sys.exit("Sorry, Python 3.0 or greater is required")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
try:
    import go
finally:
    del sys.path[0]

classifiers = """\
Development Status :: 5 - Production/Stable
Environment :: Console
Intended Audience :: Developers
License :: OSI Approved :: MIT License
Operating System :: OS Independent
Programming Language :: Python :: 3
Topic :: Software Development :: Libraries :: Python Modules
"""

doclines = __doc__.split("\n")

setup(
    name="go",
    version=go.__version__,
    maintainer="Peter Geer",
    maintainer_email="pageer@skepticats.com",
    url="http://github.com/pageer/go-posh",
    license="http://www.opensource.org/licenses/mit-license.php",
    platforms=["any"],
    py_modules=["go"],
    package_dir={"": "lib"},
    description=doclines[0],
    classifiers=filter(None, classifiers.split("\n")),
    long_description="\n".join(doclines[2:]),
)

