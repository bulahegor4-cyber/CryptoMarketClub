import unittest
from unittest.mock import patch

import CryptoMarketClub_channel as bot


class TelegramRoutingTests(unittest.TestCase):
    @patch.object(bot, "get_topic_id", return_value=None)
    @patch.object(bot.requests, "post")
    def test_message_is_not_sent_when_topic_is_missing(self, post, _topic):
        with self.assertRaisesRegex(RuntimeError, "not configured"):
            bot.send_telegram("test signal", topic="signals")
        post.assert_not_called()

    @patch.object(bot.requests, "post")
    def test_photo_is_not_sent_without_thread_id(self, post):
        with self.assertRaisesRegex(RuntimeError, "topic ID is missing"):
            bot.send_telegram_photo("test signal", "unused.png")
        post.assert_not_called()

    def test_news_text_normalizes_whitespace(self):
        self.assertEqual(
            bot.clean_news_text("Bitcoin\n\t rises   today"),
            "Bitcoin rises today",
        )


if __name__ == "__main__":
    unittest.main()
