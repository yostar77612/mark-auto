"""Dispatch frozen Windows workers after SQLite verification and before Qt.

Normal application and non-Windows helper startup retain PyInstaller's original
runtime hooks. Only the standard Windows multiprocessing child command is routed
here; command strings, resource trackers and forkservers remain upstream-owned.
"""

import sys

if sys.platform == 'win32' and getattr(sys, 'frozen', False):
    from multiprocessing.spawn import freeze_support, is_forking

    if is_forking(sys.argv):
        freeze_support()
