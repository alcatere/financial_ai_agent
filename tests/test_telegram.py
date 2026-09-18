from src.notifications.telegram import TelegramNotifier


def test_parse_confirm_with_underscore():
    assert TelegramNotifier._parse("/confirm_42") == (42, True)


def test_parse_confirm_with_space():
    assert TelegramNotifier._parse("/confirm 42") == (42, True)


def test_parse_reject():
    assert TelegramNotifier._parse("/reject_7") == (7, False)


def test_parse_unrelated_text_returns_none():
    assert TelegramNotifier._parse("hello there") is None


def test_parse_is_case_insensitive():
    assert TelegramNotifier._parse("/CONFIRM_3") == (3, True)
