"""Tests for vocabulary.py — VocabularyManager."""

import json


from vocabulary import VocabularyManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_vm(tmp_vocab_path) -> VocabularyManager:
    """Return a fresh VocabularyManager backed by a tmp file."""
    return VocabularyManager()


# ---------------------------------------------------------------------------
# load / save
# ---------------------------------------------------------------------------


class TestLoadSave:
    def test_creates_file_when_missing(self, tmp_vocab_path):
        assert not tmp_vocab_path.exists()
        vm = VocabularyManager()
        assert tmp_vocab_path.exists()
        assert vm.all() == {}

    def test_loads_existing(self, tmp_vocab_path):
        tmp_vocab_path.write_text(
            json.dumps({"corrections": {"hallo": "Hello"}}), encoding="utf-8"
        )
        vm = VocabularyManager()
        assert vm.all() == {"hallo": "Hello"}

    def test_corrupt_file_yields_empty(self, tmp_vocab_path):
        tmp_vocab_path.write_text("NOT JSON", encoding="utf-8")
        vm = VocabularyManager()
        assert vm.all() == {}

    def test_save_persists(self, tmp_vocab_path):
        vm = VocabularyManager()
        vm.add("Hallo", "Hi")
        raw = json.loads(tmp_vocab_path.read_text(encoding="utf-8"))
        assert raw["corrections"]["hallo"] == "Hi"


# ---------------------------------------------------------------------------
# add / remove / all
# ---------------------------------------------------------------------------


class TestAddRemove:
    def test_add_lower_keys_key(self, tmp_vocab_path):
        vm = VocabularyManager()
        vm.add("Hallo", "Hello")
        assert "hallo" in vm.all()

    def test_add_strips_spaces_from_value(self, tmp_vocab_path):
        vm = VocabularyManager()
        vm.add("wort", "  value  ")
        assert vm.all()["wort"] == "value"

    def test_add_preserves_newline_in_value(self, tmp_vocab_path):
        vm = VocabularyManager()
        vm.add("newline", "line1\nline2")
        assert vm.all()["newline"] == "line1\nline2"

    def test_add_preserves_tab_in_value(self, tmp_vocab_path):
        vm = VocabularyManager()
        vm.add("tab", "\tindented")
        assert vm.all()["tab"] == "\tindented"

    def test_add_ignores_empty_key(self, tmp_vocab_path):
        vm = VocabularyManager()
        vm.add("", "value")
        assert vm.all() == {}

    def test_add_ignores_whitespace_only_value(self, tmp_vocab_path):
        vm = VocabularyManager()
        vm.add("key", "   ")
        assert vm.all() == {}

    def test_remove_existing(self, tmp_vocab_path):
        vm = VocabularyManager()
        vm.add("hallo", "hello")
        vm.remove("Hallo")  # case-insensitive removal
        assert "hallo" not in vm.all()

    def test_remove_nonexistent_silent(self, tmp_vocab_path):
        vm = VocabularyManager()
        vm.remove("ghost")  # must not raise

    def test_all_returns_copy(self, tmp_vocab_path):
        vm = VocabularyManager()
        vm.add("a", "b")
        d = vm.all()
        d["a"] = "CHANGED"
        assert vm.all()["a"] == "b"


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


class TestApply:
    def _vm_with(self, tmp_vocab_path, pairs: dict) -> VocabularyManager:
        vm = VocabularyManager()
        for orig, corr in pairs.items():
            vm.add(orig, corr)
        return vm

    def test_apply_simple_replacement(self, tmp_vocab_path):
        vm = self._vm_with(tmp_vocab_path, {"hallo": "Hello"})
        assert vm.apply("hallo welt") == "Hello welt"

    def test_apply_case_insensitive_key(self, tmp_vocab_path):
        vm = self._vm_with(tmp_vocab_path, {"hallo": "Hello"})
        # "Hallo" stripped → key "hallo"
        assert vm.apply("Hallo welt") == "Hello welt"

    def test_apply_preserves_surrounding_punctuation(self, tmp_vocab_path):
        vm = self._vm_with(tmp_vocab_path, {"hallo": "Hello"})
        assert vm.apply("(hallo)") == "(Hello)"

    def test_apply_no_corrections(self, tmp_vocab_path):
        vm = VocabularyManager()
        assert vm.apply("keine änderung") == "keine änderung"

    def test_apply_empty_string(self, tmp_vocab_path):
        vm = VocabularyManager()
        assert vm.apply("") == ""

    def test_apply_multiple_tokens(self, tmp_vocab_path):
        vm = self._vm_with(tmp_vocab_path, {"a": "X", "b": "Y"})
        assert vm.apply("a b c") == "X Y c"

    def test_apply_word_not_in_corrections_unchanged(self, tmp_vocab_path):
        vm = self._vm_with(tmp_vocab_path, {"hallo": "Hello"})
        assert vm.apply("tschüss") == "tschüss"

    def test_apply_empty_corrections_dict(self, tmp_vocab_path):
        vm = VocabularyManager()
        text = "some text here"
        assert vm.apply(text) == text
