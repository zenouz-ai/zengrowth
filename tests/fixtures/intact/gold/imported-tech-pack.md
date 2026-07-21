---
title: "Intact Insurance — Technical Interview Pack"
aliases: [Intact Technical Interview, Director AI Ankur Round]
type: reference
status: active
tags: [interview-prep, intact-insurance, director-ai, technical-round]
updated: 2026-06-18
related:
  - "[[Intact Insurance — Leadership Interview Pack]]"
  - "[[Intact Insurance — Research and Intelligence Brief]]"
  - "[[Intact Insurance — Commercial Operations Pack]]"
  - "[[ZenInvest — Architecture Reference]]"
---

# Intact Insurance — Technical Interview Pack
> Director AI, Chief Data Office. Technical round with Ankur Gupta (Director Data & ML Products) and Jacob Abraham. Monday 22 June, 13:30–14:15. Virtual. 45 minutes — fast pace, straight to substance.

## Goal
Demonstrate production-grade technical credibility. Show you have shipped AI systems in regulated environments, not just talked about them. Prove you can work with Ankur's platform, complement his team, and lead a technical function.

> [!tip] If you cannot name the architecture, the eval metrics, and the business impact, they assume you were adjacent — not driving. Production context is what separates candidates in 2026.

---

## What This Round Is Really Testing

Indhira told you directly: success is whether her team likes working with you and finds collaboration useful. That is the lens for this entire interview.

They are not looking for the smartest ML engineer in the room. They are testing whether you will:

- Create impossible requirements for platform teams
- Force technology choices on engineering
- Build shadow AI platforms outside governance
- Build things that cannot be operationalised

Or whether you will:

- Partner with engineering and respect platform constraints
- Understand MLOps and data architecture as a consumer and co-creator
- Build reusable capability the whole organisation benefits from

**The most important sentence to repeat throughout:**

> "My role is not to build a separate AI organisation. My role is to enable the business by partnering with data, platform, engineering, governance, and risk teams to create reusable AI capability."

**Interview balance:**

| Area | Weight |
|------|--------|
| AI and ML | 30% |
| MLOps and Production | 30% |
| Data Platform | 20% |
| Collaboration and Leadership | 20% |

Ankur owns the ML platform. Jacob is a senior data scientist or ML engineer. They are assessing three things:

1. Can you architect and deliver production AI systems?
2. Do you understand how AI breaks in the real world and how to prevent it?
3. Will you be a credible technical leader they can work with — as a partner, not a competitor?

---

## Mock Performance Summary

| Question | Score | Priority |
|----------|-------|----------|
| Q1 — Technical architecture of AI function | 6/10 | Fix — name the tools |
| Q2 — Model drift detection | 8/10 | Minor — PSI/KS names, business metrics |
| Q3 — Class imbalance | 7/10 | Minor — threshold tuning, broker bias |
| Q4 — Model governance walkthrough | 5/10 | **Fix tonight** — tools, process, regulation |
| Q5 — RAG architecture end to end | 9/10 | Minor — hallucination handling, Guidewire |

---

## Concepts You Must Know Cold

### The Databricks Stack — One Sentence Each

**Delta Lake**
The reliable, versioned data foundation. ACID transactions, time travel, schema enforcement. Gives you the auditability regulators need — query exactly what data existed on any date in history.

**Unity Catalog**
The governance layer. Controls who accesses what data, tracks lineage from source through model to prediction, and houses the model registry. Every data and AI asset at Intact lives under Unity Catalog.

**MLflow**
The memory of your AI programme. Tracks every experiment, model version, and deployment decision. Three things: experiment tracking, model registry with approval workflows, model serving endpoints.

**Feature Store**
Guarantees features used to train a model are identical to features used in production. Eliminates the most common cause of models behaving differently in testing versus live.

**Databricks Lakehouse Monitoring**
Watches production models for data drift and concept drift. Automated alerts when thresholds are breached. Where you detect degradation before it causes business harm.

**Databricks Model Serving**
Deploys registered models as REST API endpoints. Scales automatically. Captures every request and response for audit. When the submission triage agent calls the risk scoring model, it calls a Model Serving endpoint.

### How the Stack Connects

```
Raw Data → Delta Lake (reliable, versioned, auditable)
