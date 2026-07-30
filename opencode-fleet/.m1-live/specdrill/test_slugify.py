"""Exercise the public Unicode slug canonicalizer contract."""

import unittest

from slugify import slugify


class SlugifyTests(unittest.TestCase):
    """Verify exact results, failure paths, and canonicalization invariants."""

    def test_empty_and_whitespace_only_input_return_empty_slug(self) -> None:
        """Return empty output when input contains no slug content."""
        for text in ("", " \t\n ", "---___!!!"):
            with self.subTest(text=text):
                self.assertEqual(slugify(text), "")

    def test_collapses_and_trims_whitespace_and_separator_runs(self) -> None:
        """Replace mixed separator runs with one interior hyphen."""
        self.assertEqual(slugify(" __  red\t--blue!!! green  __ "), "red-blue-green")

    def test_preserves_unicode_letters_and_normalizes_equivalent_forms(self) -> None:
        """Make canonically equivalent accented input produce the same NFC slug."""
        composed = "Café 東京"
        decomposed = "Cafe\u0301 東京"
        self.assertEqual(slugify(composed), "Café-東京")
        self.assertEqual(slugify(decomposed), "Café-東京")

    def test_preserves_mixed_scripts_numbers_and_attached_marks(self) -> None:
        """Keep Unicode content while using punctuation as a separator."""
        self.assertEqual(slugify("naïve/مرحبا १२३"), "naïve-مرحبا-१२३")
        self.assertEqual(slugify("किताब"), "किताब")

    def test_unattached_marks_do_not_cross_separator_boundaries(self) -> None:
        """Classify unattached marks before collapsing and trimming separators."""
        self.assertEqual(slugify("\u0301alpha ! \u0301 beta\u0301"), "alpha-betá")

    def test_canonical_output_is_idempotent_and_has_clean_boundaries(self) -> None:
        """Prove the canonicalizer's claimed slug invariants."""
        result = slugify("--alpha___beta!!γ--")
        self.assertEqual(result, "alpha-beta-γ")
        self.assertIsInstance(result, str)
        self.assertEqual(slugify(result), result)
        self.assertFalse(result.startswith("-"))
        self.assertFalse(result.endswith("-"))
        self.assertNotIn("--", result)
        self.assertTrue(all(character == "-" or character.isalnum() for character in result))

    def test_rejects_invalid_input_types_explicitly(self) -> None:
        """Raise TypeError rather than coercing unsupported inputs."""
        for value in (None, 42, ["text"]):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    slugify(value)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
