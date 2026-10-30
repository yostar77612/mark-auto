import urllib.parse
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def open_url(url):
    """Hand only https URLs to the system browser; nothing is rendered in-process."""
    if type(url) is not str or urllib.parse.urlsplit(url).scheme != 'https':
        return False
    return QDesktopServices.openUrl(QUrl(url))
