"""k-anonymity suppression for the public surface (SEC-05).

The public endpoints expose only aggregate counts, with a minimum cell size so a
single job can't be singled out. Naive per-cell suppression has a hole, though:
in a *partition* (e.g. every lifecycle state), if exactly one cell is hidden then
the marginal total minus the revealed cells recovers it exactly. So we add
**complementary suppression** — whenever a single cell would be hidden, the
smallest revealed cell is hidden too, forcing at least two unknowns into any
differencing attempt.

Honest limit: at audience-of-one scale the whole dataset is one known person's
job search, so this bounds *within-dataset* singling-out, not the operator's
anonymity. Cross-endpoint correlation and correlation with public job postings
remain inherent to publishing any progress at all — see the `/public` caveat.
"""

from __future__ import annotations

# Minimum bucket size before a count is revealed.
K_ANON = 5


def suppress_partition(counts: list[int]) -> tuple[list[int], int]:
    """Apply primary + complementary cell suppression to a partition of counts.

    Returns ``(public_counts, suppressed_records)`` where suppressed cells are
    zeroed in ``public_counts`` and ``suppressed_records`` is how many underlying
    records were hidden (for the ``suppressed`` field the endpoints report).
    """
    hidden = {i for i, c in enumerate(counts) if 0 < c < K_ANON}
    # Complementary: a lone hidden cell is recoverable as total - sum(revealed),
    # so also hide the smallest revealed (>= K) cell to leave >= 2 unknowns. When
    # no cell is >= K, the margin itself is < K and is suppressed by the caller.
    if len(hidden) == 1:
        revealed = [(c, i) for i, c in enumerate(counts) if i not in hidden and c >= K_ANON]
        if revealed:
            hidden.add(min(revealed)[1])
    public = [0 if i in hidden else c for i, c in enumerate(counts)]
    suppressed_records = sum(counts[i] for i in hidden)
    return public, suppressed_records


def suppress_count(count: int) -> tuple[int, int]:
    """Suppress a single standalone count (not part of a partition).

    Returns ``(public_count, suppressed_count)``.
    """
    if 0 < count < K_ANON:
        return 0, count
    return count, 0
