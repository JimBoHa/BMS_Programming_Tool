"""Cooperative retirement of locally owned temporary instance attributes."""


def restore_attribute(obj, name, previous, missing):
    exists = previous is not missing
    while exists:
        owner = getattr(previous, "_bms_scoped_attribute", None)
        if (
            not isinstance(owner, ScopedAttribute)
            or not owner.retired
            or owner.obj is not obj
            or owner.name != name
        ):
            break
        exists, previous = owner.existed, owner.previous
    if exists:
        setattr(obj, name, previous)
    else:
        obj.__dict__.pop(name, None)


class ScopedAttribute:
    def __init__(self, obj, name, replacement):
        self.obj, self.name, self.replacement = obj, name, replacement
        self.existed = name in obj.__dict__
        self.previous = obj.__dict__.get(name)
        self.retired = False
        replacement._bms_scoped_attribute = self
        setattr(obj, name, replacement)

    def close(self):
        self.retired = True
        if self.obj.__dict__.get(self.name) is self.replacement:
            missing = object()
            restore_attribute(
                self.obj, self.name, self.previous if self.existed else missing, missing
            )
