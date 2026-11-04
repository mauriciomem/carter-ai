"""The rejection counter (plan 007 step 14, freeze B5)."""

from __future__ import annotations

import multiprocessing
import stat
from pathlib import Path

import pytest

from carter.broker import counter


@pytest.fixture
def cdir(tmp_path: Path) -> Path:
    return tmp_path / ".carter"


def test_three_rejections_in_a_family_stop_it_and_another_family_is_free(cdir: Path) -> None:
    for expected in (1, 2, 3):
        assert counter.add("ses_a", cdir) == expected
    assert counter.stopped("ses_a", cdir) and not counter.stopped("ses_b", cdir)
    assert counter.count("ses_a", cdir) == 3


def test_the_file_is_0600_in_a_0700_directory(cdir: Path) -> None:
    counter.add("ses_a", cdir)
    assert stat.S_IMODE(counter.path(cdir).stat().st_mode) == 0o600
    assert stat.S_IMODE(counter.path(cdir).parent.stat().st_mode) == 0o700


def test_entries_older_than_a_day_do_not_count_and_are_dropped_on_write(cdir: Path) -> None:
    counter.add("old", cdir, now=1_000_000)
    counter.add("old", cdir, now=1_000_001)
    assert counter.count("old", cdir) == 0  # long expired against the real clock
    counter.add("new", cdir)
    assert "old" not in counter.path(cdir).read_text()


@pytest.mark.parametrize(
    "junk", ["{not json", "[1, 2]", '{"a": {"n": "x", "last": 1}}', '{"a": 1}']
)
def test_a_corrupt_file_fails_closed_and_only_the_human_reset_replaces_it(
    cdir: Path, junk: str
) -> None:
    counter.add("ses_a", cdir)
    counter.path(cdir).write_text(junk)
    with pytest.raises(counter.CounterError):
        counter.stopped("ses_a", cdir)
    with pytest.raises(counter.CounterError):
        counter.add("ses_a", cdir)
    counter.reset(cdir)
    assert counter.count("ses_a", cdir) == 0


def test_reset_clears_every_family(cdir: Path) -> None:
    counter.add("a", cdir)
    counter.add("b", cdir)
    assert counter.reset(cdir) == 2
    assert counter.summary(cdir) == (0, 0)


def test_an_odd_root_id_is_refused(cdir: Path) -> None:
    for bad in ("", "a b", "x" * 200, "a\nb", "../x"):
        with pytest.raises(counter.CounterError):
            counter.add(bad, cdir)


def _worker(args: tuple[str, int]) -> None:
    directory, n = args
    for _ in range(n):
        counter.add("race", Path(directory))


def test_concurrent_writers_do_not_lose_counts(cdir: Path) -> None:
    with multiprocessing.get_context("fork").Pool(4) as pool:
        pool.map(_worker, [(str(cdir), 5)] * 4)
    assert counter.count("race", cdir) == 20


def test_summary_counts_only(cdir: Path) -> None:
    for _ in range(3):
        counter.add("a", cdir)
    counter.add("b", cdir)
    assert counter.summary(cdir) == (2, 1)
