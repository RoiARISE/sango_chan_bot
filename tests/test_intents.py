"""Unit tests for the mention intent table in ``src.intents``."""

from __future__ import annotations

import re

from src import intents


def test_find_intent_matches_keywords_inside_the_note():
    greeting = intents.find_intent("@bot こんにちは")
    assert greeting is not None
    assert "挨拶" in greeting.build_hint()


def test_find_intent_returns_none_for_unknown_text():
    assert intents.find_intent("とくに意味のない文章") is None


def test_fixed_intents_do_not_depend_on_llm_text():
    ping = intents.find_intent("@bot ping")
    assert ping is not None
    assert ping.fixed is True
    assert ping.render_fallback("user") == "pong？"


def test_chikuwa_intent_only_applies_to_replies():
    chikuwa = intents.find_intent("@bot ちくわ大明神")
    assert chikuwa is not None
    assert chikuwa.reply_only is True
    assert chikuwa.render_fallback("user") == "…なに？"


def test_calling_intent_uses_the_display_name():
    intent = intents.find_intent("@bot さんごちゃん？")
    assert intent is not None
    assert intent.render_fallback("みー") == "どうしたの？ みーさん"


def test_time_intent_hint_contains_the_current_time():
    intent = intents.find_intent("@bot 今何時")
    assert intent is not None
    assert re.search(r"\d{2}:\d{2}:\d{2}", intent.build_hint())
