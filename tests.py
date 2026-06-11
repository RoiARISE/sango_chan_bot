import os
import tempfile
import unittest

from stores.user_store import UserStore
from utils import sanitize_nickname, validate_nickname


class Tests(unittest.TestCase):
    def test_nicknames(self):
        valid_nicknames = [
            ["\u202eほげ", "ほげ"],
            ["]$[spin ほげ", "]$\u200b[spin ほげ"],
            ["**ほげ**", "*\u200b*\u200bほげ*\u200b*\u200b"],
            ["</i>ほげ<i>", "<\u200b/i>ほげ<\u200bi>"],
            ["@sango", "@\u200bsango"],
            ["#sango", "#\u200bsango"],
            [
                "https://example.com",
                "https:\u200b//example.com",
            ],
            [
                "[ほげ](https://example.com)",
                "[ほげ]\u200b(https:\u200b//example.com)",
            ],
            [
                "https:\u202e//example.com",
                "https:\u200b//example.com",
            ]
        ]
        invalid_nicknames = [
            "\u202e",
            "　",
            " 　 　",
        ]
        for valid in valid_nicknames:
            expected = valid[1]
            actual = sanitize_nickname(valid[0])
            self.assertEqual(expected, actual)
            self.assertTrue(validate_nickname(actual))
        for invalid in invalid_nicknames:
            sanitized = sanitize_nickname(invalid)
            self.assertFalse(validate_nickname(sanitized))

    def test_user_store(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            store = UserStore(tmp_path, None, "my_id")
            store.load()
            self.assertEqual(store._data, {})

            # set nickname
            store.set_nickname("user1", "ニックネーム1", "username1")
            self.assertEqual(store.get_display_name("user1"), "ニックネーム1")

            # set profile
            store.set_profile("user1", "プログラミングが好きな人", "username1")
            self.assertEqual(store.get_profile("user1"), "プログラミングが好きな人")

            store.save()

            # load in a new instance
            store2 = UserStore(tmp_path, None, "my_id")
            store2.load()
            self.assertEqual(store2.get_display_name("user1"), "ニックネーム1")
            self.assertEqual(store2.get_profile("user1"), "プログラミングが好きな人")

            # clear nickname
            store2.clear_nickname("user1")
            self.assertEqual(store2.get_display_name("user1"), "username1")
            self.assertEqual(store2.get_profile("user1"), "プログラミングが好きな人")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


if __name__ == "__main__":
    unittest.main()
