# ZenGrowth arXiv preprint — working paper (v0.2)

**Status: architecture + pre-registered evaluation.** `main.tex` contains
**no first-hand measured figures**. Each unmeasured or partially verified claim
is stated plainly in the scorecard and maps to a procedure in
[`../../docs/HONEST-VALUE-REVIEW-PLAN.md`](../../docs/HONEST-VALUE-REVIEW-PLAN.md).
The long-term peer-reviewed study programme is in
[`../../docs/ACADEMIC-PUBLICATION-PLAN.md`](../../docs/ACADEMIC-PUBLICATION-PLAN.md).
Style follows the ZenInvest house template vendored at
[`../../docs/templates/zeninvest-arxiv/`](../../docs/templates/zeninvest-arxiv/).

## Build

```bash
latexmk -pdf main.tex
# or: pdflatex main && bibtex main && pdflatex main && pdflatex main
```

Standard TeX Live packages only (no external `.sty`). A minimal TinyTeX
install needs at least `titlesec` (and the usual `collection-latexrecommended`
fonts) via `tlmgr install titlesec`. The v0.2 source has completed a full
`latexmk`/BibTeX build and visual page review. Build artefacts
(`.aux`, `.bbl`, `.pdf`, …) are gitignored; commit source only.

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
2. **Recheck references at submission time.** Primary arXiv, publisher, and
   product pages were verified for v0.2. Product pages establish only what a
   vendor claims. Recheck mutable pages and access dates before submission.
3. **Privacy pass** (plan ground rule 4): no employer names, identifying role
   titles, salary figures, or CV text anywhere in the paper or baselines.
4. **Novelty verdict:** retain ResumeFlow and Resume Tailor as the closest
   candidate-side systems and update the precise delta if newer work appears.
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
