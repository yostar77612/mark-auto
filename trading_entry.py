"""Passive public process entry; load runtime dependencies only on launch."""

import sys


def launch(argv=None):
    """Open the unified desktop while retaining the callable recovery API."""
    from desktop import main

    arguments = list(sys.argv[1:] if argv is None else argv)
    return main(arguments or ['--platform-v2'])
