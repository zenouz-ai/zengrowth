---
title: "Technical prep pack — Intact Insurance (formerly RSA UK)"
aliases: [technical-prep-pack-intact-insurance-formerly-rsa-uk, "Intact Insurance (formerly RSA UK) — Director of AI Interview Pack"]
type: reference
status: active
tags: [interview-prep, tech-prep-pack, job-application, intact-insurance-formerly-rsa-uk]
updated: 2026-07-04
related:
  - "[[Interview Preparation]]"
---

# Technical prep pack — Intact Insurance (formerly RSA UK)

> [!tip] This is your third round with the same peer panel: Jacob (Data Platform), Chris (Data Management and Governance), and Ian (Analytics and Insights) already know your L&G story. Go deeper, not wider -- demonstrate architecture precision, fix the EU AI Act timing slip, and show how you would make each of their pillars succeed through the CoE.

---

> [!warning] Internal prep pack — not an application document. Company and interviewer facts below come from unverified web research (sources at the end). Claims about your own experience cite your verified evidence bank inline.


## Likely Technical Themes

This is a technical panel. Based on the debrief from the 22 June round and the structure of the three interviewers, expect questions to cluster tightly around five themes.

**1. AI/ML architecture on Azure and Databricks**

Jacob (Data Platform) probed hard on Gen AI infrastructure in the first round. Expect him to escalate from the high-level RAG pipeline you described toward questions about MLOps maturity, model registry design, and how an AI CoE's compute and deployment patterns sit on top of the existing data platform. Intact Insurance's commercial lines technology programme is actively embedding AI into underwriting processes, which signals the data platform team is already integrating ML workloads. You should be ready to describe your views on a Databricks-native MLOps pattern, covering Unity Catalog for model governance, MLflow for experiment tracking and registry, and Lakehouse Monitoring for drift.

**2. Responsible AI, compliance frameworks, and regulatory mapping**

Chris (Data Management and Governance) owns the governance pillar. He will want to see depth, not buzzwords. The EU AI Act, effective mid-2025, classifies financial AI applications by risk, imposing strict requirements on high-risk systems like credit assessments and fraud detection -- and insurance pricing almost certainly falls into the high-risk category. The debrief flags a factual error on EU AI Act timing under pressure: correct it proactively. You also need to speak fluently to FCA Consumer Duty implications for AI outputs, model explainability requirements, and the UK pro-innovation AI framework. The UK pro-innovation AI framework sets out five core principles -- fairness, transparency, accountability, safety, and contestability -- and emphasises a flexible, context-driven approach, which is a useful counterweight to the EU Act's rigidity when explaining how you would tier governance intensity.

**3. Gen AI and LLM deployment in an enterprise insurance context**

Artificial intelligence has moved from experimentation to execution at Intact Insurance, and in specialty lines the insurer is deliberately embedding AI without diluting human judgment. Ian (Analytics and Insights) will be interested in where LLMs add genuine value versus where they introduce risk. Be ready to discuss document ingestion and extraction, RAG evaluation (you covered four pillars in Round 1 and it landed), and how enterprise LLM deployments maintain auditability. Intact's Global Specialty Lines already envisages agentic AI allowing carrier and broker systems to interact more fluidly, and multimodal AI leveraging satellite imagery for pricing and risk evaluation.

**4. AI Centre of Excellence design and operating model**

The role's primary deliverable is establishing the AI CoE. The panel will press on how you structure it, how you balance central governance versus domain team autonomy, how you staff it, and how it partners with the parent Intact Lab. Intact established the Intact Lab more than ten years ago; today it includes over 600 employees across Montreal, Toronto and Hong Kong, focusing on automation and AI. The UK CoE will need to accelerate integration with that parent capability rather than duplicate it. Have a clear model: federated data scientists embedded in business units, reporting into a central AI Director, with shared platform, shared standards, and shared evaluation tooling.

**5. PoC-to-production discipline and change management**

Intact's own COO acknowledges "the biggest challenge is the speed of adaptation and adoption -- you're asking businesses and individuals to work in different ways, in new ways, and to get out of their comfort zones." The underwriter resistance story resonated strongly in Round 1; expect Ian or Chris to probe further on how you drive adoption at scale beyond a single use case.

---

## Likely Questions with Strong Answer Outlines

**Q1. "How would you structure the AI CoE in the first 90 days? What are the foundations you'd put down before building anything?"**

*Outline:* Avoid rushing to technology. Frame the first 30 days as listening and auditing: interview each CDO pillar director (Jacob, Chris, Ian and peers), catalogue existing models and PoCs, map data assets, and understand the CIO operating model. Days 31-60: produce a tiered use-case backlog prioritised on value-to-risk ratio; propose a governance framework covering secure AI SDLC, model cards, and a risk classification rubric that mirrors the EU AI Act's tier structure. Days 61-90: stand up the shared experimentation environment (sandbox on Databricks/Azure ML), define the CoE team shape, and establish the first quarterly showcase cadence. Anchor this to your lived L&G experience of building from scratch.

**Q2. "Walk me through how you would govern an LLM deployed in an underwriting workflow. What does responsible deployment actually look like in practice?"**

*Outline:* This is Chris's question. Start with risk classification -- is the model in the loop (human reviews every output) or in the decision (model output triggers action)? Underwriting assistance is typically in-the-loop, which reduces the EU AI Act burden. Then layer: (a) evaluation suite at build time -- groundedness, faithfulness, retrieval precision, hallucination rate; (b) model card and DecisionRecord per significant model, mapping to FCA Consumer Duty; (c) human-in-the-loop review queue for edge cases; (d) production monitoring for drift and output distribution shift; (e) incident response procedure including rollback triggers. Be specific about tooling: MLflow for registry, Lakehouse Monitoring for drift, a custom evaluation harness.

**Q3. "What's your view on the balance between building internally versus buying/partnering with AI vendors?"**

*Outline:* Intact's own instinct is to build core capabilities internally: "Our reflex is to build it and own it internally -- we want to be able to control our data and move at the pace that matches our investment priorities." Align with this instinct but add nuance: build the core differentiated models (pricing, risk, claims triage) internally; buy or partner for horizontal infrastructure (LLM API, vector stores, observability tooling); treat external partners as accelerators not substitutes. Reference the group Intact Lab as the natural internal build partner for foundational capability.

**Q4. "How do you evaluate whether a Gen AI use case is production-ready versus still a PoC?"**

*Outline:* Propose a four-gate model: (1) Technical gate -- evaluation suite passes threshold on chosen metrics (RAGAS, DeepEval, or custom); latency and cost profiles are within SLA. (2) Governance gate -- risk classification complete, model card signed off, compliance review complete, human-in-the-loop design confirmed. (3) Business gate -- clear owner in the business unit, success metric agreed, rollback plan documented. (4) Change gate -- training plan for end users, feedback channel established. Emphasise that most PoCs fail at gate 3 or 4, not gate 1, which is why CoE design must embed business partnership from day one.

**Q5. "How would you handle disagreement with Chris on a governance decision -- for example, if you wanted to move faster on a deployment than the governance framework allowed?"**

*Outline:* This is an implicit CDO-pillar collaboration question. Acknowledge the tension openly and describe it as productive. Governance exists to protect speed in the long run by preventing incidents. Propose a structured escalation: first, understand the specific concern (is it legal, reputational, technical?); second, offer a time-boxed, scoped exception with enhanced monitoring; third, use the incident to improve the framework so the next case is cleaner. Name that Chris's pillar and yours are complementary, not competing.

**Q6. "What is the EU AI Act's actual relevance to insurance pricing and how should we be preparing now?"**

*Outline:* This corrects the timing error from Round 1. The EU AI Act is effective mid-2025 and classifies financial AI applications by risk, imposing strict requirements on high-risk systems. Insurance pricing models that influence access to or terms of financial products likely fall under the high-risk classification. Obligations include: conformity assessment before deployment, technical documentation, logging and traceability, human oversight, and accuracy/robustness testing. Given Intact operates across UK, Ireland, and Europe, the EU Act applies to the European book even if the UK framework is lighter-touch. Preparation actions: complete an AI inventory and risk classification exercise; implement technical documentation standards (model cards); ensure all high-risk models have an audit trail.

---

## STAR Examples from Your Evidence

The following examples are drawn directly from the evidence bank and are structured for this panel. Each is tagged to the interviewer most likely to value it.

**Example A: Building the Enterprise AI Operating Model (governance depth for Chris)**

- **S:** An enterprise lacked any formal framework governing how AI models moved from experiment to production, creating compliance risk and duplicated effort across teams.
- **T:** Design and implement a governance framework that could scale across business units and pass regulatory scrutiny.
- **A:** [claim-f36d2622f5b88750] Designed and implemented an Enterprise AI Operating Model covering governance frameworks, a secure AI SDLC, evaluation standards, and POC-to-production deployment and monitoring standards.
- **R:** The framework created a single, auditable path from experimentation to production, reducing governance inconsistency across teams. Connect to Intact's need for a Data-Centric AI CoE with consistent standards across six CDO pillars.

**Example B: Building and Leading the AI Team at Legal and General (scale and ownership for Ian)**

- **S:** A major UK insurer had no central AI capability and fragmented data science activity across eight business units.
- **T:** Build a high-performing, multidisciplinary AI team from zero and deliver measurable commercial outcomes.
- **A:** [claim-fb88990916535807] Built and led a 10-person multidisciplinary AI team from the ground up with 208% peak budget growth, owning a £1.07M budget. [claim-28ba3474d89df2b5] This delivered £2.05M realised value and a £1.95M pipeline across 8 business units.
- **R:** Quantified commercial impact at a scale directly comparable to what Intact UK is trying to build. This is the strongest anchor example for the CoE mandate.

**Example C: FCA and EU AI Act Compliance Pack (regulatory precision for Chris)**

- **S:** A regulated financial services AI deployment needed to demonstrate compliance with emerging UK and EU regulatory frameworks, not just internal governance policy.
- **T:** Design the compliance architecture so that it was defensible to both FCA and EU AI Act scrutiny from day one.
- **A:** [claim-534dd59e64d1ab68] Embedded AI governance by design: a dual profit/customer-outcome scorecard, an auditable DecisionRecord per quote, a two-level evaluation suite, and a ~30-document compliance pack mapped to FCA Consumer Duty and EU AI Act.
- **R:** The compliance pack became a template for the wider team. Use this to directly address the EU AI Act timing correction.

**Example D: Agentic Pricing and Risk Platform (technical depth for Jacob)**
