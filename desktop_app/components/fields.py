"""Field identity and label association; input construction stays with callers."""


def named_field(widget, name, label, *, caption=None):
    if name is not None:
        widget.setObjectName(name)
    widget.setAccessibleName(label)
    if caption is not None:
        caption.setBuddy(widget)
    return widget
