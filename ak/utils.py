"""Miscelaneous utils."""

import time


class DataRecord:
    """Mutable alternative to namedtuple."""
    __slots__ = ()  # override in derived class

    def __init__(self, **kwargs):
        for n in self.__slots__:
            setattr(self, n, kwargs.pop(n, None))
            assert not kwargs, f"unexpected attributes spacified: {kwargs}"


class Timer:
    """Simple timer."""
    def __init__(self, timer_name=None, log_method=None):
        self.start = None
        self.elapsed = None
        self.log_method = log_method
        self.timer_name = timer_name

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, _exc_value, _exc_tb):
        finish = time.perf_counter()
        self.elapsed = finish - self.start
        if self.timer_name:
            result_descr = "done" if not exc_type else "failed"
            msg = f"{self.timer_name}: {result_descr} {self.elapsed: 6.3f} sec."
            if self.log_method is None:
                print(msg)
            else:
                self.log_method(msg)


class Comparable:
    """Mixin which implemets comparison operations using cmp method.

    Implement single method cmp(self, other) -> int and all the
    '>', '<', etc. operations will work.
    """
    def cmp(self, _other):
        assert False, f"implement cmp method in {type(self)}"

    def __lt__(self, other):
        return self.cmp(other) < 0

    def __gt__(self, other):
        return self.cmp(other) > 0

    def __eq__(self, other):
        return self.cmp(other) == 0

    def __le__(self, other):
        return self.cmp(other) <= 0

    def __ge__(self, other):
        return self.cmp(other) >= 0

    def __ne__(self, other):
        return self.cmp(other) != 0
