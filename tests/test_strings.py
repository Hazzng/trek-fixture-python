"""Tests for the strings module."""

from trek_fixture.strings import is_palindrome, slugify


def test_slugify_basic() -> None:
    assert slugify("Hello, World!") == "hello-world"


def test_slugify_trims_and_collapses() -> None:
    assert slugify("  Trek  Fixture  Repo  ") == "trek-fixture-repo"


def test_is_palindrome_true() -> None:
    assert is_palindrome("A man, a plan, a canal: Panama")


def test_is_palindrome_false() -> None:
    assert not is_palindrome("hello")
