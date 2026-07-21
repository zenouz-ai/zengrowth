# ZenGrowth Academic Publication Plan

**Status:** living research plan, 2026-07-21

**Current artifact:** working paper v0.2 (architecture and pre-registered evaluation)

**Decision:** publish the preprint after the first frozen measurements; pursue peer review only after the study design below is executed.

## 1. Publication verdict

ZenGrowth is worth publishing, but not as a new general-purpose agent
architecture and not yet as evidence that AI improves job-search outcomes.
Its credible academic form is a human-centred systems paper or longitudinal
field study about verification and oversight in a reputation-bearing agentic
workflow.

The current paper is useful as a transparent pre-registration. A serious
peer-reviewed submission needs empirical results, uncertainty, a reproducible
comparison, and evidence from more than the system's author.

## 2. Position relative to the field

| Comparison class | Where stronger work leads | ZenGrowth's defensible position |
|---|---|---|
| General agent benchmarks | Breadth, long-horizon tasks, many models and scenarios; for example [AgencyBench](https://arxiv.org/abs/2601.11044) evaluates 138 tasks across 32 scenarios. | Not a frontier capability benchmark. It supplies a deep, domain-specific deployment and outcome trail. |
| Agent auditability | [Auditable Agents](https://arxiv.org/abs/2604.05485) provides a general framework, dimensions, mechanisms, and multi-project evidence. | A concrete candidate-side instantiation with claim provenance, pre-action checks, approval, costs, and downstream outcomes. |
| Human oversight | [Human oversight of agentic systems in practice](https://arxiv.org/abs/2606.05391) studies 17 developers and identifies a priori control, co-planning, real-time monitoring, and post-hoc review. | A measurable workflow in another high-consequence domain, including review time and correction burden. |
| Resume generation | [ResumeFlow](https://arxiv.org/abs/2402.06221) already covers personalized resume generation and hallucination-oriented metrics. | Broader lifecycle coverage and an enforced outbound-action boundary. |
| Longitudinal career retrieval | [Career-Aware Resume Tailoring](https://arxiv.org/abs/2605.05257) already provides provenance-aware longitudinal retrieval and a nine-job case study. | The novelty cannot be longitudinal retrieval alone; it must be end-to-end audit evidence and outcome accounting. |
| Commercial career tools | Stronger product polish, user volume, integrations, and application throughput. | Local-first evidence control, explicit limitations, correction accounting, and publishable negative results. |
| Production evaluation practice | Industry guidance combines automated evals, production monitoring, and periodic human calibration; see [Anthropic's agent-evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) and [NIST's evaluation probes](https://www.nist.gov/programs-projects/building-evaluation-probes-agentic-ai). | A small-system implementation of that layered approach, with the opportunity to publish its full protocol and failure data. |

## 3. Novelty claim to test, not assume

No individual component is novel: retrieval, provenance, numeric/entity gates,
audit logs, human approval, and cost telemetry all have precedents. The
potential contribution is their evaluated combination:

1. **A reputation-bearing action boundary.** Separate reversible assistance
   (finding, ranking, drafting) from external actions whose errors affect a
   person's professional reputation.
2. **A claim-to-action audit chain.** Connect source span, extracted claim,
   generated sentence, deterministic gate result, human correction, final
   artifact, model cost, and downstream outcome.
3. **Correction burden as a first-class agent metric.** Measure what the human
   must inspect and repair, not only task completion or model latency.
4. **Denominator-complete negative-result reporting.** Publish failures,
   abandoned drafts, false positives, and applications without callbacks,
   avoiding the survivorship bias common in product marketing.
5. **A reusable evaluation protocol for candidate-side agents.** Release the
   adjudication rubric, synthetic replay tasks, aggregation code, and reporting
   schema without releasing personal career data.

These contributions remain hypotheses until the measurements and comparisons
below are complete.

## 4. Research questions

- **RQ1 -- Factual support:** What proportion of generated, externally visible
  claims are fully supported, partially supported, unsupported, or embellished?
- **RQ2 -- Guardrail value:** Which failure classes are caught by numeric/entity
  checks, and which survive until human semantic review?
- **RQ3 -- Oversight burden:** How much review and correction time does the
  verification-first workflow require, and what types of correction dominate?
- **RQ4 -- Stability:** How much do scores, ranks, selected evidence, and drafts
  vary across repeated runs, model versions, and harmless input paraphrases?
- **RQ5 -- Efficiency:** What are end-to-end elapsed time, model cost, operator
  time, and failure/retry rates per completed material set?
- **RQ6 -- Decision usefulness:** Does the ranking associate with independently
  specified pursue decisions or expert relevance judgments?
- **RQ7 -- Downstream outcomes (exploratory):** With complete denominators, what
  callback and interview rates are observed, without claiming causality from a
  small uncontrolled field deployment?

## 5. Study programme

### Phase A -- Instrumentation and frozen single-operator audit

Freeze the current system version, model identifiers, prompts, operation
inclusion rules, currency conversion source/date, and data cutoff. Produce only
aggregate, de-identified outputs.

Required artifacts:

- a machine-readable run manifest with commit, model, prompt and schema versions;
- claim-level adjudication guidelines with examples and edge cases;
- a randomly sampled grounding audit, stratified by material type and gate result;
- repeated-score and repeated-generation runs over frozen public job postings;
- end-to-end time split into system wait, model latency, human review, and correction;
- per-run cost distributions rather than averages alone;
- an egress and audit-log completeness check;
- complete job/application/outcome denominators for the observation window.

Report medians, interquartile ranges, full ranges, sample sizes, missingness,
and failures. Do not convert the existing priority score into a probability.

### Phase B -- Reproducible comparative evaluation

Create a public synthetic or consented benchmark of career histories and job
descriptions. Compare at least:

1. unassisted/manual drafting;
2. a conventional single-prompt LLM baseline;
3. ZenGrowth generation without deterministic gates;
4. the full verification-first workflow.

Use counterbalanced ordering and frozen model versions. Blind at least two
adjudicators to condition. Measure support accuracy, omissions, harmful
embellishments, correction count, review time, cost, and document usefulness.
Report inter-rater agreement and resolve disagreements using a documented third
pass. The baseline prompts and budgets must be equally capable and disclosed.

### Phase C -- Multi-user human study

Run a pilot before choosing the confirmatory sample size. A realistic serious
study would recruit participants with varied seniority and occupations, then
use the pilot variance and a declared smallest effect of interest for power
analysis. Do not choose a convenient sample and backfill a power claim.

Candidate design: within-subject, counterbalanced preparation of materials for
multiple suitable postings. Collect task time, review/correction behaviour,
NASA-TLX or another justified workload measure, trust calibration, perceived
control, and willingness to submit. Add semi-structured interviews focused on
oversight strategies and failures.

Obtain ethics/IRB review or a documented institutional determination before
recruiting. Use informed consent, data minimisation, withdrawal procedures,
retention limits, and a separate key for participant identifiers.

### Phase D -- Longitudinal field outcomes

Track a prospectively defined campaign with complete application denominators
and follow-up windows. Record material condition, participant, role family,
seniority, market/date, submission, callback, interview stages, offer, and
missing outcome status.

Treat these outcomes as exploratory unless assignment to conditions is
randomized and interference/confounding are addressed. Never optimize by
submitting extra low-quality applications merely to increase sample size.

## 6. Statistical and reporting commitments

- Define one primary endpoint before collection; recommended: externally
  visible unsupported/embellished claim rate after final review.
- Define a smallest effect of interest and power the confirmatory study from a
  pilot or defensible prior evidence.
- Use confidence intervals and effect sizes; avoid binary significance-only
  conclusions.
- Model repeated observations within participant and job rather than treating
  every generated sentence as independent.
- Publish the exclusion flow, missing-data rules, model/version changes,
  protocol deviations, and all tested outcomes.
- Separate code-based gate recall from end-to-end factual precision.
- Treat vendor match scores as product-defined signals, not callback outcomes.
- Keep exploratory downstream analyses explicitly labelled exploratory.

## 7. Reproducibility and privacy package

Public release should contain:

- paper source and rendered PDF;
- frozen protocol and analysis plan;
- aggregate measurement exporter and output schema;
- synthetic replay corpus and generation manifests;
- adjudication rubric and anonymized labels where consent permits;
- analysis scripts or notebook with environment lock;
- versioned model/provider settings and cost assumptions;
- a data statement explaining what cannot be released and why.

Never release CV text, real employer names, contact details, application
answers, private prompts containing career history, or row-level outcome data.

## 8. Venue ladder

1. **Now:** public working paper / arXiv in `cs.HC` with `cs.AI` or `cs.CL` as
   secondary classification, after Phase A measurements.
2. **Early peer feedback:** CHI, CSCW, IUI, or responsible-AI workshops; systems
   demonstration tracks if the empirical study is still small.
3. **Serious full paper:** CHI/IUI/CSCW-style human-AI interaction paper after
   Phases B and C, or an applied NLP/IR venue if the main contribution becomes
   a strong benchmark and comparative evaluation.
4. **Industry version:** an engineering experience report focused on audit
   design, correction cost, and reproducible production evaluation.

Venue calls and formatting rules change; verify them when a submission window
is selected.

## 9. Milestones and decision gates

| Gate | Deliverable | Go criterion |
|---|---|---|
| G0 | v0.2 architecture/pre-registration | Claims and public metadata pass accuracy review. |
| G1 | Frozen Phase A baseline | Every headline number reproducible from an aggregate artifact. |
| G2 | Grounding audit | Adjudication protocol usable; agreement reported; negative results retained. |
| G3 | Comparative benchmark | Fair baselines, frozen budgets, and independent labels. |
| G4 | Human-study protocol | Ethics determination, pilot, power analysis, and preregistration complete. |
| G5 | Full-paper submission | Primary endpoint, uncertainty, limitations, artifacts, and privacy statement complete. |

Stop or reposition if Phase A shows incomplete logging, if reliable semantic
adjudication cannot be achieved, or if the full workflow does not improve a
meaningful outcome over a simpler baseline. A negative result can still be a
useful paper if the protocol and failure analysis are rigorous.

## 10. Immediate next actions

1. Restore read-only VPS access and freeze the aggregate Phase A snapshot.
2. Add run/model/prompt version fields wherever a result cannot currently be
   reconstructed.
3. Write and pilot the claim-level adjudication rubric.
4. Build the synthetic replay corpus and equal-budget baseline prompts.
5. Name an independent second adjudicator or academic collaborator.
6. Select a target venue only after the Phase A and pilot evidence reveal the
   paper's strongest contribution.
