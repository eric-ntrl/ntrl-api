# NTRL - Investor One-Pager

## The Problem

News is optimized for attention, not understanding. Headlines use emotional triggers, urgency inflation, and clickbait to maximize engagement -- leaving readers anxious, polarized, and exhausted.

- 70% of Americans are "worn out" by the amount of news (Pew Research)
- News avoidance has doubled since 2017
- Trust in media at historic lows across every demographic

## The Solution

**NTRL is a filter for information.** It detects and removes manipulative language -- clickbait, hype, emotional pressure, selling, and agenda-driven framing -- so people can understand the world without being worked up.

NTRL does not add perspective or interpretation. It strips information back to its core signal: what happened, what is known, what is uncertain, and why it matters.

| Original Headline | NTRL Version |
|---|---|
| Markets PANIC as stocks plunge amid fears of collapse | Stocks decline amid investor concern over economic indicators |
| SHOCKING study changes everything you know about health | Study identifies correlation; researchers note limitations |

## How It Works

A fully automated 4-stage pipeline runs every 4 hours:

1. **INGEST** -- Pull articles from RSS across 10 feed categories
2. **CLASSIFY** -- LLM detects 14 manipulation categories (clickbait, emotional appeal, urgency inflation, false authority, etc.)
3. **NEUTRALIZE** -- LLM rewrites flagged content, preserving facts while removing distortion
4. **BRIEF ASSEMBLE** -- Curate a calm, deterministic daily brief of 250 stories

**LLM accuracy (gpt-4o-mini):** 96% precision | 77% recall | 86% F1

**10-category feed:** World, U.S., Local, Business, Technology, Science, Health, Environment, Sports, Culture

**3-tab article view:** Brief (summary) | Full (original) | Ntrl (transparency -- color-coded highlights across 4 highlight groups show exactly what was changed and why)

## Differentiation

| Feature | NTRL | Apple News | Ground News |
|---|---|---|---|
| Detects & removes manipulation | Yes | No | No |
| Shows what was changed (transparency) | Yes | No | No |
| No engagement mechanics | Yes | No | No |
| No personalization / filter bubbles | Yes | No | Partial |
| Manipulation classification | 14 categories | None | None |

## Business Model

**Phase 1 (Current):** Consumer subscription app (iOS & Android)
- Target: News-fatigued professionals, mental health-conscious users
- Price point: $5--10/month

**Phase 2:** B2B API
- License neutralization technology to publishers and platforms
- Enterprise compliance and internal communications

## Traction

- Full pipeline deployed on Railway staging (cron every 4 hours)
- 200+ articles classified and 95+ neutralized per pipeline run
- 250 stories assembled into daily brief
- React Native + Expo mobile app (iOS & Android), FastAPI backend
- 25-item codebase audit completed (security, hardening, quality, documentation)
- All systems deployed and verified on staging

## Team

**Eric Brown** -- Founder
[TBD -- background and relevant experience]

## The Ask

[TBD -- raise amount and use of funds]

## Contact

[TBD -- contact information]

---

*NTRL: Neutrality is not passive. It is disciplined refusal to distort.*
