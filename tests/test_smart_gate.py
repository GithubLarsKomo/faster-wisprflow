from smart_gate import correction_decision, normalize_correction_mode


def decide(text: str, mode: str = "smart", enabled: bool = True):
    return correction_decision(
        text,
        correction_enabled=enabled,
        mode=mode,
    )


def test_normalize_unknown_mode_to_smart():
    assert normalize_correction_mode("unknown") == "smart"


def test_disabled_bypasses_correction():
    assert not decide("Das ist ein längerer Satz.", enabled=False).use_llm


def test_fast_always_bypasses():
    result = decide("das ist absichtlich nicht sauber", mode="fast")
    assert not result.use_llm
    assert result.reason == "fast_mode"


def test_polish_preserves_always_correct_behavior():
    result = decide("Kurzer Text.", mode="polish")
    assert result.use_llm
    assert result.reason == "polish_mode"


def test_empty_smart_bypasses():
    assert not decide("   ").use_llm


def test_very_short_fragment_bypasses_without_other_signal():
    result = decide("Termin morgen zehn")
    assert not result.use_llm
    assert result.reason == "short_clean_fragment"


def test_clean_short_sentence_bypasses():
    result = decide("Der Bericht ist bereits vollständig geprüft.")
    assert not result.use_llm
    assert result.reason == "short_structurally_clean"


def test_missing_terminal_punctuation_routes_to_llm():
    result = decide("Der Bericht ist bereits vollständig geprüft")
    assert result.use_llm
    assert result.reason == "missing_terminal_punctuation"


def test_long_utterance_routes_to_llm():
    result = decide(
        "Dieser deutlich längere Satz enthält genügend Wörter dass die "
        "bestehende Korrektur im Smart Modus weiterhin ausgeführt werden soll."
    )
    assert result.use_llm
    assert result.reason == "long_utterance"


def test_adjacent_repetition_routes_to_llm():
    result = decide("Bitte bitte sende den Bericht.")
    assert result.use_llm
    assert result.reason == "adjacent_repetition"


def test_self_correction_signal_routes_to_llm_even_when_short():
    result = decide("Drei nein doch vier")
    assert result.use_llm
    assert result.reason == "self_correction_signal"


def test_unbalanced_delimiters_route_to_llm():
    result = decide("Bitte sende (den Bericht.")
    assert result.use_llm
    assert result.reason == "unbalanced_delimiters"


def test_lowercase_sentence_start_routes_to_llm():
    result = decide("der Bericht ist bereits vollständig geprüft.")
    assert result.use_llm
    assert result.reason == "lowercase_sentence_start"
