"""Test uuid short string parser."""

import unittest

from ak.short_uuid import uuid_from_short_str, uuid_to_short_str, uuid_from_str


class TestShortUuid(unittest.TestCase):
    """Test uuids conversion to and from short string from."""

    def test_uuids_short(self):
        """Test uuids conversions"""

        short_str = 'hfDoPxAatD8tiFaSAL3oXh'
        long_str = 'de22bbe0-43bf-448d-9b83-2ee57e663285'

        u1 = uuid_from_short_str(short_str)
        u2 = uuid_from_str(long_str)
        u3 = uuid_from_str(short_str)

        self.assertEqual(u1, u2)
        self.assertEqual(u1, u3, "uuid_from_str should accept both long and short strings")

        self.assertEqual(short_str, uuid_to_short_str(u1))
        self.assertEqual(long_str, str(u1))
