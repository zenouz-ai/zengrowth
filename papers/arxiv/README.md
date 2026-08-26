# ZenGrowth arXiv preprint — working paper (v0.4)

**Status: working system + prospective evaluation.** `main.tex` contains
**no first-hand measured figures**. Each unmeasured or partially verified claim
is stated plainly in the scorecard and maps to a procedure in
[`../../docs/HONEST-VALUE-REVIEW-PLAN.md`](../../docs/HONEST-VALUE-REVIEW-PLAN.md).
The long-term peer-reviewed study programme is in
[`../../docs/ACADEMIC-PUBLICATION-PLAN.md`](../../docs/ACADEMIC-PUBLICATION-PLAN.md).
Style follows the ZenInvest house template vendored at
[`../../docs/templates/zeninvest-arxiv/`](../../docs/templates/zeninvest-arxiv/).

v0.4 (2026-08) makes the present contribution explicit: ZenGrowth is a
functioning, integrated tool with useful workflow capabilities, while claims
about smoothness, speed, correctness rates, and downstream effectiveness remain
prospective measurements. It adds a capability evidence ladder, stronger pilot
minimums, research rechecked through 2026-08-26, an official Sonnet 5 source,
and corrected PDF metadata and approval-boundary rendering. Still no fabricated
statistics.

## Build

```bash
latexmk -pdf main.tex
# or: pdflatex main && bibtex main && pdflatex main && pdflatex main
```

Standard TeX Live packages only (no external `.sty`). Needs `titlesec` and
TikZ/`pgf`. A minimal TinyTeX install:

```bash
tlmgr install titlesec pgf
```

Build artefacts (`.aux`, `.bbl`, `.pdf`, …) are gitignored; commit source
only. Copy a reviewed PDF to `output/pdf/` when freezing a public render.

## Aggregate production measurements

`aggregate_measurements.py` opens the production SQLite database read-only and
prints de-identified counts and telemetry distributions. It deliberately never
selects employer names, role titles, document text, evidence text, or notes.

```bash
docker exec -i zengrowth-prod-api \
  python /app/papers/arxiv/aggregate_measurements.py /app/data/zengrowth.db
```

Do not quote `llm_cost_per_instrumented_job_usd` as application cost: v1 must
first freeze which operation names and time window constitute one application.

## Before submission (blocking checklist)

1. **Insert measured results only from frozen artifacts.** Each v1 number must
   cite a dated, committed aggregate baseline and its derivation query (plan
   ground rule 2); do not replace ``unmeasured'' with recollection.
2. **Recheck references at submission time.** Academic neighbors were rechecked
   through 2026-08-26 for v0.4, including the latest record for every cited
   arXiv identifier and new work on steerable scoring (2608.14948), employer-side
   field experiments (2507.08029v2), and human susceptibility to biased hiring
   recommendations (2509.04404v2). Product pages establish only what a vendor
   claims and were last verified 2026-07.
3. **Privacy pass** (plan ground rule 4): no employer names, identifying role
   titles, salary figures, or CV text anywhere in the paper or baselines.
4. **Novelty verdict:** Resume Tailor remains the closest longitudinal case
   study; Grounded Optimization is the closest rewrite-defense method paper.
   The remaining delta is a live approval-bound field account with correction
   burden and denominator-complete reporting — still a hypothesis until Phase A.
5. **Compile check**: full `pdflatex` + `bibtex` cycle, zero undefined
   citations, zero overfull warnings worth fixing.
6. **AI-assistance acknowledgment** retained (arXiv policy) — already in
   `main.tex`.

## arXiv submission checklist

- **Primary category (provisional): `cs.HC`** — the paper is a human–AI
  interaction field note about a supervised-autonomy system in a personal
  workflow; the measured artifact is the interaction discipline
  (verification gates + approval boundary), not a new model or algorithm.
  Cross-list: `cs.CY` (computers and society: hiring) and `cs.CL` (the
  grounding-gate NLG evaluation angle). Revisit after Phase 3: if the
  grounding audit becomes the paper's centre, `cs.CL` may take primary.
- Title/abstract within arXiv limits; abstract has no citations or markup
  that breaks the listing page.
- Single self-contained `main.tex` + `references.bib` + compiled `.bbl`
  uploaded (arXiv runs its own TeX; include the `.bbl`).
- License selection (arXiv non-exclusive license is the default choice).
- Ancillary files: none (baselines stay in the repository; the paper links
  the public mirror).
