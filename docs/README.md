# NTRL Documentation

Central documentation hub for NTRL — Neutral News.

> **Last updated:** January 2026
> **Documents:** 28 markdown files across 8 categories

---

## Business

Materials for investors and stakeholders.

| Document | Description |
|----------|-------------|
| [One-Pager](business/one-pager.md) | Investor summary — problem, solution, traction, ask |
| [Pitch Deck Outline](business/pitch-deck-outline.md) | Slide-by-slide content for presentations |
| [Competitive Analysis](business/competitive-analysis.md) | NTRL vs. Apple News, Ground News, AllSides, SmartNews, 1440 |
| [Market Analysis](business/market-analysis.md) | TAM/SAM/SOM, user personas, market trends |
| [Financial Model](business/financial-model.md) | Revenue model, unit economics, cost structure |

## Product

Product specifications and design.

| Document | Description |
|----------|-------------|
| [Product Overview](product/product-overview.md) | Canonical product spec — 5 principles, 3-tab experience, 10 categories |
| [Neutralization Spec](product/neutralization-spec.md) | Canon rules, 14 manipulation categories, implementation details |
| [Taxonomy Reference](product/taxonomy-reference.md) | 14 categories, 20 domains, 10 feed categories, mappings |
| [Content Pipeline](product/content-pipeline.md) | 4-stage pipeline: INGEST → CLASSIFY → NEUTRALIZE → BRIEF ASSEMBLE |
| [Roadmap](product/roadmap.md) | Phase 1–4 feature roadmap with technical prerequisites |

## Technical

Architecture, API, and infrastructure.

| Document | Description |
|----------|-------------|
| [Architecture Overview](technical/architecture-overview.md) | System-wide architecture — both codebases, data flow, tech stack |
| [API Reference](technical/api-reference.md) | All V1 + V2 endpoints with request/response schemas |
| [Data Model](technical/data-model.md) | Database schema — 10 tables, enums, relationships, migrations |
| [Infrastructure](technical/infrastructure.md) | Railway, PostgreSQL, S3, LLM providers, networking |

## Team

Onboarding and development standards.

| Document | Description |
|----------|-------------|
| [Onboarding Guide](team/onboarding-guide.md) | New team member setup, codebase walkthrough, key concepts |
| [Development Workflow](team/development-workflow.md) | Git workflow, testing, debugging, deployment process |
| [Engineering Standards](team/engineering-standards.md) | Python/TypeScript conventions, dark mode rules, test patterns |
| [Claude Code Guide](team/claude-code-guide.md) | AI-assisted development workflow with CLAUDE.md files |

## Operations

Deployment, monitoring, and incident response.

| Document | Description |
|----------|-------------|
| [Deployment Runbook](operations/deployment-runbook.md) | Railway auto-deploy, EAS Build, rollback procedures |
| [Monitoring Runbook](operations/monitoring-runbook.md) | Health checks, pipeline metrics, debug endpoints, alerts |
| [Incident Response](operations/incident-response.md) | P0–P3 severity levels, diagnostic trees, recovery procedures |

## Launch

App Store submission and pre-launch preparation.

| Document | Description |
|----------|-------------|
| [App Store Checklist](launch/app-store-checklist.md) | iOS + Android submission requirements, metadata, review notes |
| [Privacy Policy Draft](launch/privacy-policy-draft.md) | Privacy policy based on actual data practices `[DRAFT]` |
| [Terms of Service Draft](launch/terms-of-service-draft.md) | Terms of service with AI disclaimers `[DRAFT]` |
| [Support Playbook](launch/support-playbook.md) | Common issues, response templates, escalation path |
| [Beta Testing Plan](launch/beta-testing-plan.md) | TestFlight/Play Store testing, feedback methodology |

## Governance

Editorial policy and content sourcing.

| Document | Description |
|----------|-------------|
| [Editorial Policy](governance/editorial-policy.md) | What neutralization is/isn't, source criteria, transparency commitment |
| [Content Sourcing Policy](governance/content-sourcing-policy.md) | RSS selection, fair use, source diversity |

---

## Document Status

| Status | Count | Meaning |
|--------|-------|---------|
| Complete | 16 | Fully generated from codebase — no placeholders |
| Partial | 9 | Generated with `[TBD]` placeholders requiring founder input |
| Draft | 2 | Legal documents requiring attorney review before publication |
| Living | 1 | Roadmap — updated as decisions are made |

### Documents requiring founder input

These documents contain `[TBD — founder input needed]` placeholders:

- `business/one-pager.md` — Raise amount, founder bio, contact info
- `business/pitch-deck-outline.md` — Financials, team bios, market sizing
- `business/competitive-analysis.md` — Pricing decisions, feature timeline
- `business/market-analysis.md` — TAM/SAM/SOM figures, growth targets
- `business/financial-model.md` — Pricing, projections, CAC/LTV
- `launch/app-store-checklist.md` — App description, keywords, developer account
- `launch/support-playbook.md` — Support email, escalation contacts
- `launch/beta-testing-plan.md` — Timeline, beta group size, success criteria
- `product/roadmap.md` — Phase timelines, pricing decisions

### Documents requiring legal review

These documents are marked `[DRAFT — REQUIRES ATTORNEY REVIEW BEFORE PUBLICATION]`:

- `launch/privacy-policy-draft.md`
- `launch/terms-of-service-draft.md`

---

## Primary Source References

These files are the authoritative source material from which documentation was generated:

| Source | Location | Used For |
|--------|----------|----------|
| Backend CLAUDE.md | `code/ntrl-api/CLAUDE.md` | Architecture, pipeline, API, data model, operations |
| Frontend CLAUDE.md | `code/ntrl-app/CLAUDE.md` | Product overview, UI architecture, design system |
| Neutralization Canon | `code/ntrl-api/docs/canon/neutralization-canon-v1.md` | Canon rules, priority system |
| Content Spec | `code/ntrl-api/docs/canon/content-spec-v1.md` | 6-output spec, content generation rules |
| AGENTS.md | `AGENTS.md` | Engineering standards, development workflow |

## Historical PDF References

The following PDFs predate this documentation suite. They remain available for reference but the markdown documents above are now the canonical versions.

| PDF | Location | Superseded By |
|-----|----------|---------------|
| Brand & Product Canon v1.0 | `brand/NTRL_Brand_and_Product_Canon_v1.0.pdf` | `product/product-overview.md` |
| UX Language Rules v1.0 | `brand/NTRL_UX_Language_Rules_v1.0.pdf` | `team/engineering-standards.md` |
| UX Copy Templates v1.0 | `brand/NTRL_UX_Copy_Templates_v1.0.pdf` | `team/engineering-standards.md` |
| Homepage Copy v1.1 | `brand/NTRL_Homepage_Copy_v1.1.pdf` | `business/one-pager.md` |
| Wireframe Spec v1.1 | `Screen Mocks/NTRL_Phase-1_Wireframe_Spec_v1.1.pdf` | `product/product-overview.md` |
| Technical Architecture v1.0 | `NTRL_Canonical_Documents_Master_v1.0/` | `technical/architecture-overview.md` |
| Content Ingestion Strategy v1.0 | `NTRL_Canonical_Documents_Master_v1.0/` | `product/content-pipeline.md` |
| Frontend-Backend Spec v1.0 | `NTRL_Frontend_Backend_Responsibility_Spec_v1.0.pdf` | `technical/architecture-overview.md` |
| Redline Checklist v1 | `NTRL_Canonical_Documents_Master_v1.0/` | `launch/app-store-checklist.md` |

---

## Contributing

When adding or updating documentation:

1. Use lowercase filenames with hyphens: `my-document.md`
2. No version numbers in filenames — track versions in the file header
3. Place in the appropriate subdirectory
4. Update this index
5. Include a `Last Updated` date in the document header
