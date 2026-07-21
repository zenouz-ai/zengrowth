---
title: "Debrief — Director of Data + Governance + Transformation"
aliases: [debrief-director-of-data-governance-transformation, "Intact Insurance (formerly RSA UK) — Director of AI Interview Pack"]
type: reference
status: active
tags: [interview-prep, debrief, job-application, intact-insurance-formerly-rsa-uk]
updated: 2026-07-04
related:
  - "[[Interview Preparation]]"
---

# Debrief — Director of Data + Governance + Transformation

---

> [!warning] Internal debrief — private to you. Observations are grounded in your transcript or notes; anything from web research cites its source at the end.


## How it went

This was the technical interview round held on 22 June 2026, conducted jointly by Jacob (Director, Data Platform), Chris (Director, Data Management and Governance), and Ian (Director, Analytics and Insights). The three interviewers represent three of the six CDO pillars that will be peer functions to the Director of AI, which makes this panel structurally significant: these are the people who will need to trust and work with you day to day.

The panel opened with a deliberate tone-setter from Ian: "This is not some interrogation... we're very nice people." That informality continued throughout, but beneath it the technical bar was real and probing. Jacob led on infrastructure and architecture questions around the Gen AI use case; Chris led on governance frameworks and change management; Ian led on technology strategy and stakeholder influence. The session ran well over the originally implied time, closing with Ian describing the role's ambition in considerable detail, which is a genuine buying signal. His closing statement that "we will be in touch pretty soon" and the warmth of the goodbyes suggest the panel left the conversation positively disposed.

Overall read: a conditional pass. The narrative around the L&G underwriting use case was strong and resonated. The governance answer was thoughtful and principled. However, two specific technical moments introduced uncertainty, and one factual error around EU AI Act timing was made under mild pressure. These are fixable, but they need to be addressed before any final-round conversation.

---

## What went well

**The anchor use case was detailed, end-to-end, and genuinely relevant.** Walking the panel through the medical records summariser at L&G, from Azure Document Intelligence ingestion through semantic chunking, vector embedding, RAG retrieval, and GPT-4o generation to a React web app interface, gave the interviewers a complete picture of hands-on delivery capability. Quantifying the business case at roughly "£1 million benefit per year" from a 30% time saving was exactly the right commercial framing for an insurance audience.

**The RAG evaluation framework answer was architecturally sound.** Describing groundedness, relevance, retrieval accuracy, and faithfulness as four evaluation pillars for an LLM pipeline is correct and defensible practice. The explanation of using a second LLM as a judge to score chunk relevance against a query is a well-established pattern. Jacob's follow-up probes on this were quite specific and the answers held.

**The governance framework answer was genuinely differentiated.** Rather than describing governance abstractly, the response grounded it in tooling, MLFlow for model registry and lifecycle tracking, Unity Catalog for data governance, and Lakehouse Monitoring for drift detection. The risk-tiering argument, calibrating governance intensity to the cost of getting a prediction wrong, is exactly the right heuristic for a financial services firm and it landed well with Chris.

**The change management answer showed leadership maturity.** The example of repositioning a Gen AI summariser tool, from something underwriters resisted to a productivity multiplier that would make them "five times faster," mirrored almost exactly a strong example from the earlier recruiter screen round. It reinforced a consistent narrative. Framing AI literacy as the primary lever for cultural adoption, and tying it to showing a live, working use case, is the right senior-leader answer.

**The technology governance philosophy was sensible and well-articulated.** The response to Ian's question about staying ahead of the technology curve, advocating for structured experimentation with time-boxed two-to-three-week POCs, business-case discipline before adoption, and avoiding blanket bans, was exactly the maturity level the role demands. The phrase "let's create a business case for it" in response to a hypothetical about Claude was a strong, memorable line.

**The motivation answer was authentic and timely.** When asked what attracts you to this world, the response connected the greenfield nature of the Intact AI function, the team dynamic observed across rounds, and genuine enthusiasm for insurance use cases such as pricing, underwriting, and claims. Ian's extended monologue about the company's ambitions following this answer suggests the candidate's enthusiasm was met and matched.

---

## What could be better

**The Azure AI Foundry versus Azure ML Studio distinction was fumbled under pressure.** Jacob asked a precise question about how Azure AI Foundry was organised in the previous role. The candidate hedged with "when you say foundry, the latest foundry, because there's foundry Classic Foundry New," and then conflated Azure ML Studio with Azure AI Foundry, saying "I thought you could do Azure ML inside foundry itself." Jacob corrected this. Azure AI Foundry (formerly Azure AI Studio and Azure OpenAI Studio) and Azure Machine Learning Studio are distinct platforms that serve different purposes. Azure AI Foundry simplifies building with generative AI, while Azure Machine Learning gives full control over custom model development. A common enterprise pattern is for Azure ML Studio to handle custom model training for predictive analytics, while Azure AI Foundry handles all LLM-based applications. This distinction should be crisp at Director of AI level; any hesitation here erodes technical credibility with a senior data platform peer.

**The multi-tenant Foundry architecture answer was underspecified.** When Jacob asked how you would organise Foundry across multiple lines of business such as claims, underwriting, and pricing, the answer described giving each department "their own workspace." Azure AI Foundry's hub-and-project model is specifically designed for enterprise multi-team governance: a central hub holds shared resources and policies, while separate projects are created for different teams or use cases. The hub-and-project nomenclature and governance model was not named, which would have been the precise, confident answer Jacob was looking for.

**The EU AI Act compliance date cited was technically imprecise.** During the governance answer, the claim was made that "the EU AI Act is coming into force 2nd of August," implying imminent full enforcement. Rules for general-purpose AI and governance infrastructure did apply from 2 August 2025, but the majority of AI Act rules, including those for high-risk AI systems, come into force on 2 August 2026. Specifically, the 2 August 2026 deadline covers full applicability of high-risk AI system compliance, including conformity assessments and EU database registration. Since the interview took place on 22 June 2026, the accurate and much more impactful point to make was that full enforcement of the high-risk AI rules was only six weeks away at the time of the interview. Citing the wrong milestone is a credibility risk with a governance-focused peer like Chris.

**The dev/staging/production answer was thin on LLM-specific MLOps.** When Jacob asked about the route-to-live approach for the Gen AI use case, the answer covered data redaction in dev and integration into existing underwriting software in production, but did not address LLM-specific concerns such as prompt versioning, model version pinning, latency monitoring, or cost-per-inference tracking. The admission that "ML Flow... I can't remember while I was there, I used it on a different project" was honest but left a gap in the architecture narrative.

**The orchestration answer was incomplete.** Jacob asked what tool handled orchestration of the RAG pipeline. The answer described the React front end and an API layer but did not name an orchestration framework such as LangChain, Semantic Kernel, or Azure Prompt Flow. For a Director-level role overseeing ML engineers deploying LLM solutions on Azure, this level of architecture specificity is expected.

---

## Gaps exposed

**Azure AI Foundry hub-and-project governance model.** The candidate was unable to describe Foundry's enterprise multi-tenancy architecture by name. Azure AI Foundry is Microsoft's answer to enterprise AI lifecycle and governance, centralising governance, compliance, and deployment pipelines while integrating with Azure ML for training, Azure AI Studio for app building, and GitHub for CI/CD. Closing this gap is a priority before any final round with Jacob or a CIO-level stakeholder.

**LLM orchestration frameworks.** The RAG pipeline was built and deployed but the orchestration layer was not named. Whether Semantic Kernel, LangChain, LlamaIndex, or Azure Prompt Flow was used, having a crisp answer here is necessary.

**LLMOps lifecycle tooling.** The candidate was stronger on traditional MLOps (MLFlow, model registries) than on LLM-specific lifecycle management, including prompt versioning, token cost monitoring, and model deprecation management in production.

**EU AI Act timeline precision.** The phased application of the Act is a compliance governance detail that Chris, as the data governance lead, will know. The Act was fully applicable from 2 August 2026, with earlier milestones for prohibitions from February 2025 and GPAI model governance from August 2025. Being able to map the three milestone dates and their specific obligations to Intact's insurance use cases (particularly pricing and underwriting models, which may qualify as high-risk systems) is a direct requirement for the role.

**Commercial lines insurance specificity.** Ian explicitly flagged that commercial lines is "very different than personal lines in terms of data volumes." The candidate acknowledged this without substantiating it with commercial lines examples. The L&G experience, if it was predominantly personal or group life, should be contextualised more carefully against commercial and specialty lines use cases.

---

## Learnings for the next stage

1. **Memorise the Azure AI Foundry hub-and-project architecture cold.** Be able to draw out: Foundry hub (shared compute, credentials, policies) and projects per line of business or use case (underwriting, claims, pricing). Azure AI Foundry builds on Azure ML concepts and DevOps/MLOps best practices, adding enterprise-level model lifecycle management and multi-model governance into one centralised platform. Be precise that Azure ML Studio is the right tool for custom tabular model training (pricing GLMs, reserving models), while Foundry is the right layer for LLM deployment and governance. Many enterprises use both platforms together: Foundry serves as the interface for deploying generative AI experiences, while Machine Learning handles traditional predictive models and experimentation.

2. **Prepare a complete EU AI Act cheat-sheet anchored to Intact's use cases.** The three key dates are: February 2025 (prohibitions and AI literacy in force), August 2025 (GPAI model and governance obligations in force), and August 2026 (high-risk AI systems fully in scope). As of August 2026, operators of AI systems that have the potential to bring significant consequences for individuals must be compliant, including models used in fields like biometrics, critical infrastructure, education, employment, or financial services. Map this to Intact: pricing models that determine premiums and underwriting models that affect policy decisions are plausible candidates for high-risk classification. Frame this proactively, not reactively, when governance comes up.

3. **Prepare a named LLM orchestration stack.** For the L&G use case, clarify retroactively which orchestration layer was used (Prompt Flow, LangChain, custom FastAPI, etc.) and be ready to compare them. For Intact's greenfield environment, prepare a recommendation: the hub-and-project model in AI Foundry maps well to how enterprises organise teams, with a central hub holding shared resources and policies and separate projects for different teams or use cases. Azure Prompt Flow within Foundry is the natural orchestration recommendation for an Azure-first insurer.

