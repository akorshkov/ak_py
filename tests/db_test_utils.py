"""Helper methods to be used in tests."""

from contextlib import closing
from functools import wraps

import sqlite3


def using_memory_db(test_method):
    """Decorator for tests which use sqlite memory db."""

    @wraps(test_method)
    def decorated_test(self):
        db = sqlite3.connect(":memory:")
        with closing(db):
            test_method(self, db)

    return decorated_test
