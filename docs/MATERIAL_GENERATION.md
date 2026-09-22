# Material Generation

ZenGrowth generates tailored CVs, cover letters, and application answers from
verified evidence claims with source provenance (claims auto-verify above a
confidence bar when their cited span checks out; the rest queue for operator
review). Deterministic gates reject selected
unsupported numeric and entity tokens, but they do not prove sentence-level
entailment; the operator reviews every externally visible artifact. All
examples below are synthetic.

## Evidence bank

Knowledge sources (uploads, pastes, inbox) are parsed, chunked, and extracted
into discrete claims with provenance (`src/zengrowth/knowledge/`). Each verified
claim has an `evidence_id` and a source span. High-confidence claims with a
verified span auto-approve (`KNOWLEDGE_AUTO_VERIFY_THRESHOLD`, default 0.75); the
rest queue in the review queue.

A synthetic evidence item looks like:

```
## evi-led-001
- category: leadership
- source_role: Head of Data Science, Northwind Robotics
- verified: true
- tags: leadership, hiring, team-building
- claim: |
    Grew a data science team from 3 to 14 engineers over 24 months against a
    published competency framework.
```

## Generation flow

`src/zengrowth/materials/generator.py` (with `evidence.py`, `cv_alignment.py`):

1. **Select evidence (RET-01).** Load a broad pool of verified claims
   (`EVIDENCE_CANDIDATE_POOL`, default 200), **relevance-rank the whole pool**
   against the job description, then keep the top `EVIDENCE_PROMPT_LIMIT`
   (default 40) for both the prompt and the grounding corpus. Ranking before the
   cap prevents a highly relevant but lower-confidence claim from being truncated.
2. **Tailor.** A Claude call (strict, grounded) realigns the summary and lightly
   reorders existing content. CV generation is **structure-preserving**: it keeps
   your template intact rather than rewriting it.
3. **Ground & validate.** Generated bullets are checked against the evidence
   corpus. Numeric/entity gates reject detectable unsupported tokens; semantic
   support remains part of operator review and the published evaluation plan.
4. **Render.** `latex.py` compiles to PDF; output is also available as TeX and
   Markdown (`files.py`). A page-fit loop then nudges the CV toward its intended
   length (1.85-1.98 pages) — and every rewrite it asks the model for is gated:
   a shortening pass may not introduce a figure, named entity, or content word
   absent from the CV and the evidence/job context, and may not change the number
   of capability lines, bullets, or sections (so the CV still round-trips through
   the structured editor); a typography pass may not change the document's words
   at all. Because a word-level check cannot see content removed by a *construct*,
   LaTeX comments are stripped first (counting backslash parity, so `\\%` is a
   line break plus a comment) and neither pass may introduce a command or
   environment outside a typography allowlist — otherwise `\iffalse`, `\phantom`,
   white text (`\textcolor` / scoped `\color`), or a `comment` environment would hide a line from the PDF without
   changing a single word. Existing hiding constructs are fingerprinted
   brace-/depth-aware (optional `\textcolor[...]` args, scoped `\color` groups,
   nested TeX `\iffalse` primitives), so relocating text into them is rejected too. A rejected or non-compiling rewrite leaves the last
   good `.tex` in place, and the review data is re-derived from the post-fit
   document. `tailoring.page_fit` always stores applied and rejected rounds,
   including when every rewrite is rejected and the `.tex` is unchanged.

Fit tier widens grounding for stronger matches:
`CV_ALIGNED_FIT_THRESHOLD` (70) and `CV_PRIORITY_FIT_THRESHOLD` (75) — priority
roles add employer/domain synonyms to the grounding query while the
no-invention gates stay on. At the default (**strict**) tier the job side of the
grounding corpus is the job *header* only (company, title, location, hybrid
policy, stated compensation), so a tool or figure that appears only in the
posting cannot ground a CV claim; the higher tiers add the JD text and summary.
No tier grounds on the scorer's own rationale.

## Revision

`revise.py` supports plain-language edits — e.g. "shorten the summary" or
"add Kubernetes" (only if Kubernetes is in your evidence). Revisions are versioned
and re-validated; you preview, request changes, then mark final.

## Candidate identity

The candidate identity printed on materials (name, contact line) comes from local
configuration. In this public mirror the default identity is the synthetic
"Jordan Avery"; operators set their own values locally and never commit them.

## Retention

Generated materials live on local disk under gitignored paths and are subject to
`MATERIALS_RETENTION_DAYS` (default 30) via `retention.py`, run either as an
opt-in daily job (`MATERIALS_RETENTION_PURGE_ENABLED`) or manually
(`python -m zengrowth.materials.retention purge`). They are never
committed and never part of the public mirror. Interview-scoped internal materials
group per `(job_id, material_type, interview_id)` so one round's latest debrief
does not purge another's.

## Internal interview materials (INT-02…05)

Employer-facing CVs, cover letters, and answers use the grounding flow above.
**Internal** materials (`audience=internal`) serve the post-application journey:

| Type | Endpoint | Notes |
|------|----------|-------|
| Prep pack | `POST /jobs/{id}/materials/pack` | Three-tier content policy (`material_policy.py`): foundation briefing (job-level, generate once), round prep keyed by `round_type` (anchor sentence, `### Q1…` questions, checklist), hybrid debrief schema (gaps with *answer to learn*). Obsidian-style envelope; optional `enhance` + `source_material_id` merges evidence into an imported skeleton; types: `company_briefing`, `interviewer_pack`, `tech_prep_pack`, `final_round_pack` |
| Debrief | `POST /jobs/{id}/interviews/{iid}/debrief` | Goal / Outcome / Gaps To Close / New Organisational Intelligence from transcript **or** round notes (`can_debrief`); same Obsidian envelope |
| Email draft | `POST /jobs/{id}/materials/email-draft` | Never-sent banner; no outbound send |
| Simulator prompt | `POST /jobs/{id}/materials/sim-prompt` | Deterministic composition; zero LLM cost |
| Import | `POST /jobs/{id}/materials/import` | File existing Obsidian/chat research packs; frontmatter and callouts preserved |

Internal artifacts expand inline on the Job detail timeline with a styled markdown
preview (frontmatter metadata, Obsidian callouts, scrollable up to ~70vh).

Prior debriefs, prior prep packs (generated and imported), and verified
`interview_learning` claims feed prep-pack prompts. YAML frontmatter is stripped
before truncation. Post-generation quality warnings (anchor, question count, line
budget, gap scripts) are audit-logged. Promoted learnings enter the review queue
as draft facts (tagged per job) — never auto-verified.
