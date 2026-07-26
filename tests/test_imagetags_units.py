"""Unit tests for pure imagetags helpers (naming + timestamp parsing)."""

from imagetags.name_methods import base36_encode, is_acceptable_name
from imagetags.time_methods import extract_timestamp


def test_base36_encode() -> None:
    assert base36_encode("0") == "0"
    assert base36_encode("10") == "g"  # hex 0x10 = 16 = 'g'
    assert base36_encode("ff") == "73"  # hex 0xff = 255 = 7*36 + 3
    # Result only uses the base36 alphabet
    assert set(base36_encode("deadbeef")) <= set("0123456789abcdefghijklmnopqrstuvwxyz")


def test_is_acceptable_name_accepts_valid() -> None:
    assert is_acceptable_name("cat_dog")
    assert is_acceptable_name("sunset_beach_walk")  # 2 underscores is the max


def test_is_acceptable_name_rejects_invalid() -> None:
    assert not is_acceptable_name("cat")  # needs at least one underscore
    assert not is_acceptable_name("_cat")  # leading underscore
    assert not is_acceptable_name("cat_")  # trailing underscore
    assert not is_acceptable_name("a_b_c_d")  # more than two underscores
    assert not is_acceptable_name("cat-dog")  # hyphen not allowed
    assert not is_acceptable_name('cat"dog')  # quote not allowed


def test_extract_timestamp_human_readable() -> None:
    assert extract_timestamp("IMG_20210609_225212") == "2021:06:09 22:52:12"
    # Date-only filenames resolve to midnight
    assert extract_timestamp("MG_20210609") == "2021:06:09 00:00:00"


def test_extract_timestamp_whatsapp_style_date() -> None:
    assert extract_timestamp("IMG-20230201-WA0000") == "2023:02:01 00:00:00"


def test_extract_timestamp_returns_empty_when_absent() -> None:
    assert extract_timestamp("random_photo_name") == ""


def test_extract_timestamp_ignores_invalid_dates() -> None:
    # 2021-13-45 is not a real date and must be rejected
    assert extract_timestamp("IMG_20211345") == ""
