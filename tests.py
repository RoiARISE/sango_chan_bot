import unittest
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


if __name__ == "__main__":
    unittest.main()
