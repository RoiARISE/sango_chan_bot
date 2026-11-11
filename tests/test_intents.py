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
    cases = {
        "@bot ping": "pong？",
        "@bot ping!!!": "pong？",
        "@bot PING": "pong？",
        "@bot にゃーん": "にゃ〜ん",
        "@bot さんごちゃーん": "は〜い",
        "@bot さんごちゃ〜ん": "は〜い",
    }
    for text, expected in cases.items():
        intent = intents.find_intent(text)
        assert intent is not None, text
        assert intent.fixed is True, text
        assert intent.render_fallback("user") == expected, text


def test_ping_does_not_match_inside_english_words():
    for text in (
        "@bot I was sleeping",
        "@bot wrapping",
        "@bot helping",
        "@bot typing",
        "@bot shopping",
    ):
        assert intents.find_intent(text) is None, text


def test_nadenade_hint_says_sango_is_the_one_being_petted():
    intent = intents.find_intent("@bot なでなで")
    assert intent is not None
    hint = intent.build_hint()
    assert "さんご" in hint
    assert "撫でられ" in hint


def test_chikuwa_intent_only_applies_to_replies():
    chikuwa = intents.find_intent("@bot ちくわ大明神")
    assert chikuwa is not None
    assert chikuwa.reply_only is True
    assert chikuwa.render_fallback("user") == "…なに？"


def test_chikuwa_question_is_not_a_fixed_command():
    assert intents.find_intent("@bot ちくわ大明神って何？") is None
    assert intents.find_intent("@bot ちくわ大明神 について教えて") is None


def test_calling_intent_uses_the_display_name():
    intent = intents.find_intent("@bot さんごちゃん？")
    assert intent is not None
    assert intent.render_fallback("みー") == "どうしたの？ みーさん"


def test_time_intent_hint_contains_the_current_time():
    intent = intents.find_intent("@bot 今何時")
    assert intent is not None
    assert re.search(r"\d{2}:\d{2}:\d{2}", intent.build_hint())


def test_help_intent_matches_various_phrases():
    phrases = (
        "@bot 何ができるの？",
        "@bot なにができる？",
        "@bot できること教えて",
        "@bot 機能教えて",
        "@bot 機能一覧",
        "@bot ヘルプ",
    )
    for phrase in phrases:
        intent = intents.find_intent(phrase)
        assert intent is not None, phrase
        assert intent.fixed is False, phrase
        hint = intent.build_hint()
        assert "機能" in hint
        fallback = intent.render_fallback("user")
        assert "ダイスロール" in fallback
        assert "あだ名" in fallback
        assert "回線速度" in fallback

