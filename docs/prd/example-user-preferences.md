# PRD: User Preferences

**Status**: draft
**Author**: Example
**Created**: 2024-01-12
**Updated**: 2024-01-12

## Overview

Allow users to customize their news brief experience by setting preferences for topics, sources, and delivery format. This enables personalized neutral news consumption.

## Problem Statement

### User Pain Points
- Users receive the same generic brief regardless of interests
- No way to filter out topics users don't care about
- Can't prioritize preferred news sources

### Current Limitations
- Briefs are one-size-fits-all
- No user identity or preference storage
- All sources treated equally

## Goals

### Must Have
- [ ] Store user preferences in database
- [ ] Filter brief content based on user topic preferences
- [ ] API endpoints to get/set preferences

### Should Have
- [ ] Source priority weighting
- [ ] Preferred brief length setting

### Nice to Have
- [ ] Time-of-day delivery preferences
- [ ] Topic notification thresholds

## User Stories

As a news reader, I want to select my preferred topics so that my brief focuses on what I care about.

As a news reader, I want to prioritize certain sources so that I see more content from outlets I trust.

## Technical Requirements

### API Changes
- `GET /v1/users/{id}/preferences` - Retrieve user preferences
- `PUT /v1/users/{id}/preferences` - Update user preferences
- `GET /v1/brief?user_id={id}` - Filtered brief by preferences

### Data Model Changes
- New `UserPreference` model with topic weights and source priorities
- Migration to create preferences table

### Dependencies
- None (uses existing database)

### Constraints
- Preferences must not slow down brief generation significantly
- Must handle users with no preferences (default behavior)

## Success Metrics

- Preference API latency < 100ms
- Brief generation with preferences < 2x baseline

## Out of Scope

- User authentication (assume user_id is provided)
- Preference sync across devices
- Machine learning preference inference

## Open Questions

- [ ] What is the default behavior for new users?
- [ ] How many topic categories should we support?
