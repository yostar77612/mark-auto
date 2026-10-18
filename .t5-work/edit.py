from pathlib import Path
import re
ui=Path('desktop_ui.py'); s=ui.read_text(encoding='utf-8')
base=re.search(r"        self.setStyleSheet\('''(.*?)'''\)",s,re.S)
market=Path('desktop_market.py'); m=market.read_text(encoding='utf-8')
market_style=re.search(r"DARK_STYLE = '''(.*?)'''",m,re.S)
colors=set(re.findall(r'#[0-9a-fA-F]{6}',base[1]+market_style[1]))
names={'#101720':'background','#dbe4ef':'text','#2563ba':'primary','#82c9ae':'success','#f1b65c':'warning','#ff8282':'danger','#a9c8ee':'neutral','#f58b8b':'market_rise','#76d6b0':'market_fall','#e8c37a':'market_warning','#502b30':'notification_error','#213b50':'notification_info','#e8f1ff':'notification_text'}
colors.update(names)
for c in sorted(colors): names.setdefault(c,'color_'+c[1:])
head='''"""Application QSS and presentation tokens; widgets select styles via properties."""
from PySide6.QtWidgets import QApplication

COLORS = '''+repr({names[c]:c for c in sorted(colors)})+'''
FONT_SIZES = {'body': 14, 'hint': 12, 'page_title': 22, 'market_title': 20}
SPACING = {'label': 3, 'input': 7, 'button_vertical': 9, 'button_horizontal': 14}
STATUS_COLORS = {state: COLORS[state] for state in ('success', 'warning', 'danger', 'neutral')}

'''
qss=base[1]+market_style[1]+'''
QPushButton[role="secondary"] { background: transparent; color: #dbe4ef; border: 1px solid #526b87; }
QPushButton[role="secondary"]:hover { background: #1b4f9b; }
QPushButton[role="secondary"]:disabled { background: #243448; color: #9aabbc; }
QLabel[themePart="pageTitle"] { font-size:22px; font-weight:600; }
QWidget#market_dashboard QLabel#market_title { font-size:20px; font-weight:700; }
QWidget#market_dashboard QGroupBox[themePart="marketCard"] { padding:3px; }
QWidget#market_dashboard QLabel#market_message { color:#e8c37a; }
QWidget#market_dashboard QLabel[status="success"] { color:#76d6b0; }
QWidget#market_dashboard QLabel[status="danger"] { color:#f58b8b; }
QWidget#market_dashboard QLabel[status="neutral"] { color:#dbe4ef; }
QLabel[status="success"] { color:#82c9ae; }
QLabel[status="warning"] { color:#f1b65c; }
QLabel[status="danger"] { color:#ff8282; }
QLabel[status="neutral"] { color:#a9c8ee; }
QLabel#local_notification[status="neutral"] { background:#213b50; color:#e8f1ff; padding:10px; border-radius:6px; }
QLabel#local_notification[status="danger"] { background:#502b30; color:#e8f1ff; padding:10px; border-radius:6px; }
QWidget[feedback="true"] { border:2px solid #82c9ae; }
'''
# Resolve token placeholders on every build, keeping the QSS readable and centralized.
for c,name in names.items(): qss=qss.replace(c,'@'+name+'@')
for size,name in [(22,'page_title'),(20,'market_title'),(14,'body'),(12,'hint')]: qss=qss.replace('font-size:'+str(size)+'px','font-size:@font_'+name+'@px').replace('font-size: '+str(size)+'px','font-size: @font_'+name+'@px')
head+='_QSS = '+repr(qss)+'''\n

def build_app_stylesheet():
    """Return all application styles, including scoped market overrides."""
    result = _QSS
    for name, value in COLORS.items():
        result = result.replace('@' + name + '@', value)
    for name, value in FONT_SIZES.items():
        result = result.replace('@font_' + name + '@', str(value))
    return result


def apply_theme(app=None):
    """Apply once at QApplication scope; individual widgets keep empty QSS."""
    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError('A QApplication is required')
    stylesheet = build_app_stylesheet()
    if app.styleSheet() != stylesheet:
        app.setStyleSheet(stylesheet)


def set_theme_property(widget, name, value):
    """Refresh Qt's cached property selectors after a presentation change."""
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_status(widget, state):
    if state not in STATUS_COLORS:
        raise ValueError('Unknown status state: ' + str(state))
    set_theme_property(widget, 'status', state)


def status_for_color(color):
    """Bridge the existing stop_presentation colour contract without changing it."""
    return next(state for state, value in STATUS_COLORS.items() if value == color)
'''
Path('desktop_theme.py').write_text(head,encoding='utf-8')
s=s[:base.start()]+'        apply_theme()'+s[base.end():]
s=s.replace('from desktop_strings import ui_text','from desktop_theme import apply_theme, set_status, set_theme_property, status_for_color\nfrom desktop_strings import ui_text')
s=s.replace("title.setStyleSheet('font-size:22px;font-weight:600')", "title.setProperty('themePart', 'pageTitle')")
s=s.replace("original = widget.styleSheet()\n        widget.setStyleSheet('border:2px solid #82c9ae;')\n        QTimer.singleShot(1800, widget, lambda: widget.setStyleSheet(original))", "original = widget.property('feedback')\n        set_theme_property(widget, 'feedback', True)\n        QTimer.singleShot(1800, widget, lambda: set_theme_property(widget, 'feedback', original))")
s=s.replace("self.paper_card.label.setStyleSheet('color:' + color)","set_status(self.paper_card.label, status_for_color(color))")
s=s.replace("        color = '#502b30' if error else '#213b50'\n",'')
s=s.replace("self.notification.setStyleSheet(f'background:{color};color:#e8f1ff;padding:10px;border-radius:6px')", "set_status(self.notification, 'danger' if error else 'neutral')")
ui.write_text(s,encoding='utf-8')
m=m[:market_style.start()]+m[market_style.end():]
m=m.replace('from desktop_strings import ui_text','from desktop_theme import apply_theme, set_status\nfrom desktop_strings import ui_text')
m=m.replace("self.setObjectName('market_dashboard'); self.setStyleSheet(DARK_STYLE)","self.setObjectName('market_dashboard'); apply_theme()")
m=m.replace("title.setStyleSheet('font-size:20px;font-weight:700;'); ",'')
m=m.replace("group.setStyleSheet('QGroupBox { padding:3px; }')","group.setProperty('themePart', 'marketCard')")
m=m.replace("self.message.setStyleSheet('color:#e8c37a;')","set_status(self.message, 'warning')")
m=m.replace("label.setStyleSheet('color:#dbe4ef;')","set_status(label, 'neutral')")
m=m.replace("label.setStyleSheet('color:'+('#f58b8b' if change is not None and change>0 else '#76d6b0' if change is not None and change<0 else '#dbe4ef')+';')", "set_status(label, 'danger' if change is not None and change>0 else 'success' if change is not None and change<0 else 'neutral')")
market.write_text(m,encoding='utf-8')
