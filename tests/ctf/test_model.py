# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib

import pytest

from carbon.ctf.catalog import bundled_challenges
from carbon.ctf.model import Challenge, CtfError, check_flag, load_challenges, normalize


def _ch(match, **flag):
    return Challenge(id="x", title="t", category="c", difficulty="intro",
                     briefing="b", flag_match=match, **flag)


def test_normalize_is_space_insensitive_and_lower():
    assert normalize("  CARBON{ Dead Beef }  ") == "carbon{deadbeef}"


def test_check_flag_exact_and_case_insensitive():
    c = _ch("exact", flag_value="CARBON{deadbeef}")
    assert check_flag(c, "carbon{DEADBEEF}")
    assert check_flag(c, " CARBON{dead beef} ")
    assert not check_flag(c, "CARBON{cafe}")


def test_check_flag_regex():
    c = _ch("regex", flag_pattern=r"CARBON\{[0-9a-f]{8}\}")
    assert check_flag(c, "CARBON{a43cb70d}")
    assert not check_flag(c, "CARBON{xyz}")


def test_check_flag_hash_hides_answer():
    secret = "CARBON{a43cb70d}"
    digest = hashlib.sha256(normalize(secret).encode()).hexdigest()
    c = _ch("hash", flag_sha256=digest)
    assert check_flag(c, secret)
    assert check_flag(c, "carbon{A43CB70D}")
    assert not check_flag(c, "CARBON{0000}")


def test_load_rejects_unknown_match(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("- {id: a, title: t, category: c, difficulty: intro, briefing: b, "
                 "flag: {match: bogus}}\n", encoding="utf-8")
    with pytest.raises(CtfError):
        load_challenges(p)


def test_load_rejects_dangling_requires(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("- {id: a, title: t, category: c, difficulty: intro, briefing: b, "
                 "requires: [ghost], flag: {match: exact, value: x}}\n", encoding="utf-8")
    with pytest.raises(CtfError):
        load_challenges(p)


def test_bundled_catalog_loads_and_is_well_formed():
    chs = bundled_challenges()
    assert len(chs) >= 5
    ids = {c.id for c in chs}
    # every prerequisite resolves, every flag has a matcher payload
    for c in chs:
        assert set(c.requires) <= ids
        assert c.flag_match in ("exact", "regex", "hash")
        if c.flag_match == "hash":
            assert c.flag_sha256
