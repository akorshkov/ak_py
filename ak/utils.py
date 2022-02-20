"""Miscelaneous utils."""


class DataRecord:
    """Mutable alternative to namedtuple."""
    __slots__ = ()  # override in derived class

    def __init__(self, **kwargs):
        for n in self.__slots__:
            setattr(self, n, kwargs.pop(n, None))
            assert not kwargs, f"unexpected attributes spacified: {kwargs}"
