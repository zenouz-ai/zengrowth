# Roadmap

This roadmap separates **shipped** from **planned**. ZenGrowth is **Beta** and
labels maturity honestly — partial work is marked partial, not implied as done.
It intentionally omits private prioritization, timelines, and target-employer
strategy.

## Shipped

- **ATS ingestion** — Greenhouse + Lever public JSON, dedupe, age filtering, and
  a bounded LLM-free precheck.
- **Explainable scoring** — single strict-JSON Claude call returning per-dimension
  scores, a rationale stored on the row, and an observable-fit priority score
  (`temperature=0` is a reproducibility control; repeated-run stability remains
  an evaluation target).
- **Paste-to-fill** — manually add a job by pasting its description.
- **Evidence-constrained materials** — structure-preserving CV tailoring, cover
  letters, and answers with numeric/entity gates plus operator review;
  PDF/TeX/Markdown export; page-fit
  guard; plain-language revision. Generation prompts enforce quantified-impact,
  authentic-voice writing with a JD-specific cover-letter hook, and every material
  carries a deterministic **JD match report** (keyword coverage score,
  matched/missing terms, quantified-line count, cliché check) — computed without
  any extra LLM spend and shown beside the preview.
- **Knowledge bank** — parse → chunk → extract facts with provenance; auto-verify
  high-confidence claims only when the cited span exists in the source *and* the
  claim's figures/entities match that span (distortions stay draft for review);
  alias/fuzzy entity resolution merges surface variants ("Acme" / "Acme Inc")
  onto one canonical node; review queue for the rest; JD-relevance evidence
  selection.
- **Evidence coverage map** — every fact (and every scored JD summary) is
  tagged against a closed, operator-extendable facet vocabulary (industry, role
  family, project type, capability, location, seniority); out-of-vocabulary
  values are rejected, not invented. A **Coverage** tab shows the verified
  evidence treemap, evidence accumulating over time, and a coverage-vs-demand
  heatmap that flags gaps ("JDs ask for X; no verified fact answers it").
  Facets are derived metadata — the verification path is untouched.
- **React/Vite dashboard** — pipeline board, job detail with rationale and interview
  journey, knowledge and review surfaces, insights, observability/traces, and an
  anonymous public view.
- **Security & ops** — operator auth, fail-closed boot, encrypted keyring, login
  backoff, k-anonymized public surface, ingestion heartbeat + `/health/ready`
  probe, and a default-off daily LLM-spend ceiling.
- **Live audit feed** — SSE stream of ingest/score/edit/interview events.
- **Deterministic eval gates** — LLM-free CI gates over hand-labelled golden
  sets: hard-fact faithfulness (no ungrounded figure/entity ever passes),
  retrieval recall, entity-resolution pairwise F1, claim-vs-span distortion
  checks, and a scoring calibration suite (rewording stability, hand-ranked
  monotonicity, anchor drift alarm).
- **Interview workflow** — dated, backdatable rounds; three-tier prep/debrief
  content policy; web-researched prep packs with provenance profile and *Enhance
  with ZenGrowth* for imported skeletons; expanded learning loop; transcript
  debriefs; email drafts; promote-a-learning; deterministic simulator prompt.
  Operator replay + judged eval (INT-06) remain open; fixture quality gates ship in CI.
- **Offer stage** — paste an offer email or upload the PDF/DOCX letter to prefill the
  terms (review-first extraction; the letter never enters the evidence bank), generate a
  market-benchmarked evaluation with provenance-labelled web research (revised offers
  are additionally judged against the prior offer and your sent counter), and draft the
  acceptance / counter-offer / clarification email (never sent by the app); offer
  status keeps the outcome funnel in sync. On acceptance, an **onboarding pack** turns
  the whole process — stakeholders, debrief intelligence, offer terms, verified
  evidence — into a 30/60/90 start plan, and a **departure pack** plans leaving the
  current role well: notice arithmetic, resignation letter, manager conversation,
  handover plan, and the leaving checklist.

## Partial

- **Dashboard breadth** — core operator workflows are in place; additional
  analytics and polish are ongoing.
- **Interview pack quality** — deterministic INT-06 fixture tests and enhance
  mode are shipped; operator replay freeze and optional LLM-as-judge eval remain.
- **Retrieval** — evidence is selected by JD relevance over verified claims.
  Chunk embeddings are computed-on-ingest only and are not yet read by any
  retrieval path (off by default).

## Planned

The forward direction is a **supervised-autonomy agentic track**: the agent
plans, researches, drafts, and queues; the operator approves everything
outbound. Auto-apply is deliberately out of scope — never-sent banners and
approval gates are the product's identity.

- **Orchestration core** — stateful multi-step runs over the existing
  capabilities with retries and human-in-the-loop pause / approve / resume.
- **Proactive planner** — a goal-directed action queue that watches apply
  windows and gaps and proposes next actions for one-click approval.
- **Approval-gated email** — recruiter thread tracking with drafts queued for
  the operator to send; nothing leaves the machine unapproved.
- **Dual-agent scoring** — a second-pass critique/verification step, gated on
  beating the single agent on the calibration suite.
- **Outcome-driven adaptation** — tune ranking weights and source selection
  from the outcome funnel once enough data accumulates.
- **Semantic / hybrid retrieval** — a retriever that actually consumes the chunk
  embeddings.

> Items under "Planned" are forward-looking and not yet implemented. Public
> claims in this repo describe only shipped behavior.
