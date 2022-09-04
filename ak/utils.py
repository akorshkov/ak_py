"""Miscelaneous utils."""

import time
from .color import ColorFmt


class DataRecord:
    """Mutable alternative to namedtuple."""
    __slots__ = ()  # override in derived class

    def __init__(self, **kwargs):
        for n in self.__slots__:
            setattr(self, n, kwargs.pop(n, None))
            assert not kwargs, f"unexpected attributes spacified: {kwargs}"


class Timer:
    """Simple timer."""
    def __init__(self, timer_name=None, report_start=False, log_method=None):
        self.start = None
        self.elapsed = None
        self.log_method = log_method
        self.timer_name = timer_name
        self.report_start = report_start

    def __enter__(self):
        if self.report_start and self.timer_name is not None:
            msg = f"{self.timer_name}: start..."
            if self.log_method is None:
                print(msg)
            else:
                self.log_method(msg)
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


def compare_dictionaries(dict_0, descr_0, dict_1, descr_1, *, lines_limit=10):
    """Print differences between two dictionaries."""
    print(f"{descr_0}:  {len(dict_0)}")
    print(f"{descr_1}:  {len(dict_1)}")

    text_ok = ColorFmt('GREEN')("Ok  ")
    text_fail = ColorFmt('RED')("Fail")

    extra_items = {
        k: v
        for k, v in dict_0.items()
        if k not in dict_1
    }
    missing_items = {
        k: v
        for k, v in dict_1.items()
        if k not in dict_0
    }
    for comment, diff_map in [
        (f"extra items in '{descr_0}'", extra_items),
        (f"extra items in '{descr_1}'", missing_items),
    ]:
        note_text = text_fail if diff_map else text_ok
        print(f"{note_text}: {len(diff_map)} {comment} detected")
        for i, (k, v) in enumerate(diff_map.items()):
            if lines_limit is not None and i >= lines_limit:
                print(f"  ... {len(diff_map) - lines_limit} skipped")
                break
            print(f"  {k}: {v}")

    diff_map = {}
    for k, v_0 in dict_0.items():
        if k in dict_1:
            v_1 = dict_1[k]
            if v_1 != v_0:
                diff_map[k] = (v_0, v_1)

    note_text = text_fail if diff_map else text_ok
    print(f"{note_text}: {len(diff_map)} items have different values")
    if diff_map:
        print(f"  key: value in '{descr_0}' vs value in '{descr_1}'")
    for i, (k, (v_0, v_1)) in enumerate(diff_map.items()):
        if lines_limit is not None and i >= lines_limit:
            print(f"  ... {len(diff_map) - lines_limit} skipped")
            break
        print(f"  {k}: {v_0} vs {v_1}")
