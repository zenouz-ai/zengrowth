# Dashboard

The dashboard is a React 19 + Vite + TypeScript SPA (`frontend/`). In dev it
runs on `:3000` and proxies `/api` and `/health` to the FastAPI backend on
`:8000`. All examples below are synthetic.

## Page map

| Page (`frontend/src/pages/`) | Purpose |
|------------------------------|---------|
| `Login.tsx` | Operator login (protected app). |
| `Setup.tsx` | First-run wizard: connect and validate the Claude key. |
| `Dashboard.tsx` | Overview / landing. |
| `Pipeline.tsx` | Curated board of scored roles and their stage. |
| `Discover.tsx` | Optional Tavily link discovery. |
| `AddJob.tsx` | Paste-to-fill a job description manually. |
| `JobDetail.tsx` | Full score rationale, EV, employer materials, the **interview journey** (`InterviewTimeline`, `JourneyRail`) — rounds, prep packs, debriefs, email drafts, simulator prompt — and the **Offer** panel (`OfferPanel`) — terms, market/negotiation-aware evaluation, response drafts, onboarding + departure packs. |
| `ReviewQueue.tsx` | Approve extracted facts before they enter the evidence bank. |
| `Knowledge.tsx` / `KnowledgeGraph.tsx` | Manage knowledge sources and the fact graph. |
| `Library.tsx` | Knowledge home: documents, facts to review, and the evidence Coverage tab (`Coverage.tsx`). |
| `Insights.tsx` | Funnel and pipeline decision analytics. |
| `Observability.tsx` / `Traces.tsx` | Per-call LLM cost/latency and traces. |
| `DataGovernance.tsx` | Data handling / retention surface. |
| `PublicDashboard.tsx` | Anonymous, k-anonymized public view. |

## API split

The dashboard talks to the backend through namespaced routers
(`src/zengrowth/api/routers/`):

| Area | Example endpoints | Auth |
|------|-------------------|------|
| Jobs / pipeline | `/api/jobs`, `/api/jobs/{id}` | operator |
| Interviews | `/api/jobs/{id}/interviews`, `/api/jobs/{id}/interviews/{iid}/transcript`, `/api/jobs/{id}/interviews/{iid}/debrief`, `/api/jobs/{id}/interviews/{iid}/promote-learning`, `/api/jobs/{id}/materials/pack`, `/api/jobs/{id}/materials/import`, `/api/jobs/{id}/materials/email-draft`, `/api/jobs/{id}/materials/sim-prompt` | operator |
| Offers | `/api/jobs/{id}/offers`, `/api/jobs/{id}/offers/extract`, `/api/jobs/{id}/offers/extract-file`, `/api/jobs/{id}/offers/{oid}/evaluate`, `/api/jobs/{id}/offers/{oid}/response-draft`, `/api/jobs/{id}/materials/onboarding-pack`, `/api/jobs/{id}/materials/departure-pack` | operator |
| Ingestion | `/api/ingestion/...` | operator |
| Discovery | `/api/discovery/...` | operator |
| Knowledge | `/api/knowledge/...` | operator |
| Observability | `/api/observability/...` | operator |
| Audit / events | `/api/audit`, `/api/events` (SSE) | operator |
| Settings | `/api/settings/...` | operator |
| Health | `/health`, `/health/ready` | open |
| Public view | `/api/public/...` | open, aggregate only |

Every `/api/*` route except the public view requires an operator session. The
public view returns only aggregate, k-anonymized counts with complementary
suppression so a hidden cell cannot be recovered by differencing.

## Live updates

The audit feed streams over Server-Sent Events (`/api/events`), so ingest,
score, and edit activity appears in the dashboard as it happens (gated by the
`FEATURE_SSE` flag).

## Interview journey (Job detail)

The **Interview journey** panel on `JobDetail.tsx` drives the post-application
workflow:

| Action | UI | API |
|--------|-----|-----|
| Add / edit round | *Add interview round* (optional script/transcript field), **Edit dates**, status dropdown | `POST/PATCH /api/jobs/{id}/interviews` |
| Paste transcript | *Paste transcript or notes* (or supply when adding the round) | `PUT .../transcript` or `transcript` on create |
| Generate debrief | *Generate debrief* (enabled when `can_debrief` — transcript or round notes) | `POST .../debrief` |
| Prep packs | *Regenerate foundation briefing* (job) / *Prep for this round* (per round); *Enhance with ZenGrowth* when an imported pack exists | `POST .../materials/pack` (`enhance`, `source_material_id` optional) |
| Import artifact | *Import a pack or note* — link round-specific imports from the round card so the learning loop can reuse them | `POST .../materials/import` |
| Email draft | *Draft an email* | `POST .../materials/email-draft` |
| Save learning | *Save a learning* → Approve facts queue (scoped per job on the rail) | `POST .../promote-learning` |
| Simulator | *Simulator prompt* (zero LLM cost) | `POST .../materials/sim-prompt` |

List rows expose `has_transcript` and `can_debrief`. Outcome sync when adding
rounds is forward-only and skips terminal jobs (rejected/offer/archived).

## Offer panel (Job detail)

The **Offer** panel closes the journey once a process reaches an offer:

| Action | UI | API |
|--------|-----|-----|
| Record / revise offer | *Record an offer* / *record a revised offer* — terms form with backdatable dates and offer-letter paste | `POST/PATCH /api/jobs/{id}/offers` |
| Extract terms | Paste the offer email or upload the PDF/DOCX letter — prefills the form for review | `POST .../offers/extract`, `POST .../offers/extract-file` |
| Evaluate | *Evaluate against the market* — web-researched benchmark vs. market and your expectations; revised offers also get a **Movement From Last Round** section vs. the prior offer and your sent counter | `POST .../offers/{oid}/evaluate` |
| Respond | *Draft a response* — acceptance / counter-offer / clarification with the never-sent banner | `POST .../offers/{oid}/response-draft` |
| Decide | Status dropdown (received → evaluating → negotiating → accepted / declined / withdrawn) | `PATCH .../offers/{oid}` |
| Onboard | *Generate onboarding pack* (shown once accepted) — 30/60/90 start plan from the whole process | `POST .../materials/onboarding-pack` |
| Depart | *Plan your departure* (shown once accepted) — resignation letter, handover, leaving checklist | `POST .../materials/departure-pack` |

Recording an offer moves the outcome funnel to `offer`; accepting or declining
stamps the terminal result. A respond-by countdown appears while the offer is live.

## Frontend structure

Route pages are code-split via `React.lazy` in `src/App.tsx` (recharts loads only
with chart pages). Brand fonts are self-hosted; iOS home-screen tiles use
pre-rendered PWA icons (`frontend/README.md` has the full component map and
mobile notes).
