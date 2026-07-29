# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import string

from hypothesis import given
from hypothesis import strategies as st

from core import auth

identity_alphabet = string.ascii_letters + string.digits + ":._-"
identity_st = st.text(alphabet=identity_alphabet, min_size=1, max_size=128)
token_st = st.text(alphabet=string.ascii_letters + string.digits, min_size=16, max_size=128)
label_st = st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), max_size=64)
key_st = st.text(max_size=8192)


@given(identity_st, token_st, label_st, key_st)
def test_well_formed_request_is_accepted(
    identity: str, token: str, label: str, public_key: str
) -> None:
    assert auth.valid_access_request(identity, token, label, public_key) is True


@given(token_st, label_st, key_st)
def test_oversized_identity_is_rejected(
    token: str, label: str, public_key: str
) -> None:
    assert auth.valid_access_request("a" * 129, token, label, public_key) is False


@given(identity_st, label_st, key_st)
def test_short_token_is_rejected(identity: str, label: str, public_key: str) -> None:
    assert auth.valid_access_request(identity, "tooshort", label, public_key) is False


@given(identity_st, token_st, label_st)
def test_oversized_public_key_is_rejected(identity: str, token: str, label: str) -> None:
    assert auth.valid_access_request(identity, token, label, "x" * 8193) is False
