"""SEC-05: k-anonymity suppression primitives (primary + complementary)."""

from __future__ import annotations

from zengrowth.api.kanon import K_ANON, suppress_count, suppress_partition


def test_suppress_count_hides_below_threshold():
    assert suppress_count(0) == (0, 0)
    assert suppress_count(K_ANON - 1) == (0, K_ANON - 1)
    assert suppress_count(K_ANON) == (K_ANON, 0)
    assert suppress_count(99) == (99, 0)


def test_partition_reveals_when_no_small_cells():
    public, suppressed = suppress_partition([10, 0, 7])
    assert public == [10, 0, 7]
    assert suppressed == 0


def test_partition_complements_a_lone_small_cell():
    # One small cell (3) would be recoverable as total - sum(revealed); hide the
    # smallest revealed cell (5) too so two unknowns remain.
    public, suppressed = suppress_partition([3, 5, 20])
    assert public == [0, 0, 20]
    assert suppressed == 8


def test_partition_two_small_cells_need_no_complement():
    public, suppressed = suppress_partition([3, 4, 20])
    assert public == [0, 0, 20]
    assert suppressed == 7


def test_partition_lone_small_cell_with_no_revealed_cell():
    # Nothing >= K to hide; the margin (=3) is itself < K and suppressed upstream.
    public, suppressed = suppress_partition([3, 0, 0])
    assert public == [0, 0, 0]
    assert suppressed == 3


def test_partition_picks_smallest_revealed_as_complement():
    public, suppressed = suppress_partition([2, 9, 6, 50])
    # 2 is hidden; smallest revealed is 6 -> hidden too.
    assert public == [0, 9, 0, 50]
    assert suppressed == 8
