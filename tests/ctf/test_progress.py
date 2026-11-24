# SPDX-License-Identifier: GPL-3.0-or-later
from carbon.ctf.catalog import AVAILABLE, LOCKED, SOLVED, bundled_challenges, status_of
from carbon.ctf.progress import load_progress


def test_progress_roundtrip(tmp_path):
    p = tmp_path / "prog.json"
    prog = load_progress(p)
    assert not prog.is_solved("a")
    prog.mark_solved("a")
    prog.reveal_hint("a")
    # reloaded from disk
    again = load_progress(p)
    assert again.is_solved("a")
    assert again.hints_used("a") == 1


def test_progress_reset_clears(tmp_path):
    p = tmp_path / "prog.json"
    prog = load_progress(p)
    prog.mark_solved("a")
    prog.reset("a")
    assert not load_progress(p).is_solved("a")


def test_missing_file_is_fresh_start(tmp_path):
    prog = load_progress(tmp_path / "nope.json")
    assert prog.solved_ids() == set()


def test_status_gating_with_requires(tmp_path):
    chs = {c.id: c for c in bundled_challenges()}
    prog = load_progress(tmp_path / "prog.json")
    # a gated challenge starts locked
    gated = next(c for c in chs.values() if c.requires)
    assert status_of(gated, prog) == LOCKED
    # an ungated one is available
    free = next(c for c in chs.values() if not c.requires)
    assert status_of(free, prog) == AVAILABLE
    # solving the prerequisites unlocks it
    for req in gated.requires:
        prog.mark_solved(req)
    assert status_of(gated, prog) == AVAILABLE
    prog.mark_solved(gated.id)
    assert status_of(gated, prog) == SOLVED
