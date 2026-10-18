import re
from keel.connect.codes import new_user_code, new_device_code

_UC = r"[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{4}-[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{4}"


def test_user_code_shape_and_alphabet():
    assert re.fullmatch(_UC, new_user_code())


def test_user_codes_are_distinct():
    assert len({new_user_code() for _ in range(200)}) > 190  # overwhelmingly unique


def test_device_code_is_long_and_urlsafe():
    dc = new_device_code()
    assert len(dc) >= 40 and re.fullmatch(r"[A-Za-z0-9_\-]+", dc)
