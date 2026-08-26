# Source of Truth — SYNTHETIC evidence bank (public test fixture only)

This is a fully synthetic evidence bank for the fictional candidate
"Jordan Avery". It exists so the material-generation test suite has verified
claims to ground against in the public mirror. It contains no real personal
data, no real employers, and no real metrics.

In the private canonical repo this path holds the operator's real, verified
career evidence, which is never published.

Each `## evidence_id` block is one verified claim, in the format the evidence
parser expects (see `src/zengrowth/materials/evidence.py`).

---

## evi-profile-001
- category: profile
- source_role: Head of Data Science, Northwind Robotics
- verified: true
- tags: leadership, ai, strategy
- claim: |
    Senior AI and data science leader who has built and scaled teams, shipped
    production machine learning, and aligned delivery to enterprise strategy.

## evi-led-001
- category: leadership
- source_role: Head of Data Science, Northwind Robotics
- verified: true
- tags: leadership, hiring, team-building
- claim: |
    Built and led a data science team against a published competency and
    hiring framework, mentoring engineers across multiple product areas.

## evi-tech-001
- category: technical
- source_role: Lead AI Engineer, Acme FinTech
- verified: true
- tags: ml, mlops, platforms
- claim: |
    Designed and shipped production machine learning models and MLOps pipelines
    on a cloud platform, partnering with leadership on AI roadmaps.

## evi-imp-001
- category: impact
- source_role: AI Strategy Lead, Globex Health
- verified: true
- tags: strategy, delivery, impact
- claim: |
    Turned applied research into reliable products and aligned a delivery
    roadmap to measurable business outcomes across the organization.
