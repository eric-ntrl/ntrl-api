# NTRL Neutralization Canon v1.0

**Status**: FOUNDATIONAL / LOCKING DOCUMENT

## 1. Purpose

The NTRL Neutralization Canon defines what it means for an article to be neutralized.
Neutralization removes language pressure while preserving meaning, uncertainty, and attribution.

## 2. Scope

**Applies to**: Article neutralization outputs including neutral headlines, briefs, and extracted facts.

**Does not apply to**: Fact checking, editorial explanation, opinion classification, viewpoint balancing, or sentiment scoring.

## 3. Priority Structure

Rules are ordered by priority:
1. **A - Meaning Preservation** (highest)
2. **B - Neutrality Enforcement**
3. **C - Attribution & Agency Safety**
4. **D - Structural Constraints** (lowest)

Higher priority rules override lower ones.

## 4. Canon Rules

### A. Meaning Preservation

| Rule | Description |
|------|-------------|
| A1 | No new facts may be introduced |
| A2 | Facts may not be removed if doing so changes meaning |
| A3 | Factual scope and quantifiers must be preserved |
| A4 | Compound factual terms are atomic (e.g., domestic abuse, sex work) |
| A5 | Epistemic certainty must be preserved exactly |
| A6 | Causal facts are not motives |

### B. Neutrality Enforcement

| Rule | Description |
|------|-------------|
| B1 | Remove urgency framing |
| B2 | Remove emotional amplification |
| B3 | Remove agenda or ideological signaling unless quoted and attributed |
| B4 | Remove conflict theater language |
| B5 | Remove implied judgment |

### C. Attribution & Agency Safety

| Rule | Description |
|------|-------------|
| C1 | No inferred ownership or affiliation |
| C2 | No possessive constructions involving named individuals unless explicit |
| C3 | No inferred intent or purpose |
| C4 | Attribution must be preserved |

### D. Structural & Mechanical Constraints

| Rule | Description |
|------|-------------|
| D1 | Grammar must be intact |
| D2 | No ALL-CAPS emphasis except acronyms |
| D3 | Headlines must be ≤12 words |
| D4 | Neutral tone throughout |

## 5. Pass / Fail Definition

An output passes if and only if **all canon rules pass**. One failure equals no ship.

## 6. Implementation Relationship

- **Models** generate neutral language within canon boundaries
- **Post-processors** enforce deterministic guarantees
- **Graders** evaluate binary rule compliance

## 7. Versioning

This document is v1.0. Changes require:
- Explicit rationale
- Version increment
- Regression testing

## 8. Final Principle

> If an output feels calmer but is less true, it fails.
> If it feels true but pushes the reader, it fails.
