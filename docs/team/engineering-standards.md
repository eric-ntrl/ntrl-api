# Engineering Standards

Code conventions and engineering standards for NTRL.

---

## Python (Backend — code/ntrl-api/)

- **Framework:** FastAPI with SQLAlchemy ORM
- **Style:** `snake_case` for modules and functions, 4-space indentation
- **Config:** pydantic-settings for environment variable validation (`app/config.py`)
- **Constants:** Centralized in `app/constants.py` (`TextLimits`, `PipelineDefaults`, etc.)
- **Models:** SQLAlchemy models with docstrings explaining purpose and relationships
- **Tests:** `test_*.py` files in the `tests/` directory, run with pytest
- **Dependencies:** Pipenv with all versions pinned

---

## TypeScript (Frontend — code/ntrl-app/)

- **Framework:** React Native with Expo
- **Style:** Prettier and ESLint enforced, strict mode enabled
- **Tests:** `*.test.ts` files, Jest + React Testing Library
- **E2E:** Playwright specs in `e2e/`
- **Linting:** `npm run lint`, `npm run lint:fix`, `npm run format`

---

## Dark Mode (CRITICAL)

All frontend screens MUST use dynamic styles that respond to theme changes. Static style objects will not update when the user toggles dark mode.

```typescript
// CORRECT — styles rebuild when theme changes
const { theme } = useTheme();
const styles = useMemo(() => createStyles(theme), [theme]);

function createStyles(theme: Theme) {
  return StyleSheet.create({
    container: {
      backgroundColor: theme.colors.background,
    },
  });
}

// WRONG — will not respond to dark mode
import { colors } from '../theme';
const styles = StyleSheet.create({
  container: {
    backgroundColor: colors.background,
  },
});
```

Every frontend PR that touches UI must be verified for dark mode support before merging.

---

## API Design Patterns

- **Schemas:** Pydantic request/response schemas defined in `app/schemas/`
- **Auth:** Admin endpoints protected by `X-API-Key` header with timing-safe comparison
- **Fail closed:** Return 500 if `ADMIN_API_KEY` is not set in environment
- **Error responses:** Sanitized messages only; never expose stack traces to clients
- **Rate limiting:** slowapi — 100/min global, 10/min admin endpoints, 5/min pipeline endpoints
- **Caching:** TTLCache for brief (15 min TTL), stories (1 hr TTL)

---

## Database Conventions

- **Primary keys:** UUID on all tables
- **Migrations:** Alembic (always verify single head before committing)
- **Indexes:** Added on frequently queried columns
- **Denormalization:** `DailyBriefItem` carries denormalized fields for fast reads, avoiding joins at query time

---

## LLM Integration Patterns

- **Provider architecture:** Pluggable providers in `neutralizer/providers/`; swap implementations via `NEUTRALIZER_PROVIDER` env var
- **Status tracking:** Always record neutralization status (`success`, `failed_llm`, `failed_garbled`) in the database
- **No mock in production:** Never use `MockNeutralizerProvider` as a production fallback
- **Failed articles:** Tracked in DB but excluded from user-facing output
- **Prompt encoding:** Use Unicode escapes for special characters in prompts (e.g., `\u2014`), not literal characters, to avoid encoding issues across environments

---

## Security Standards

- **Auth comparison:** `secrets.compare_digest` for all API key checks (timing-safe)
- **SSL:** Verify certificates on all outbound HTTP requests
- **CORS:** Restricted to explicitly configured origins
- **Secrets management:** No secrets in code; use environment variables exclusively
- **Dependencies:** All versions pinned to prevent supply-chain drift

---

## Testing Standards

- **Backend:** pytest for all tests; mark LLM-dependent tests with `@pytest.mark.llm` so they can be skipped in fast CI runs
- **Frontend:** Jest for unit and component tests, Playwright for end-to-end tests
- **Gold standard corpus:** Span detection accuracy validated against fixtures in `tests/fixtures/gold_standard/`
- **Expected failures:** Tests known to fail with the mock provider are documented; do not suppress them silently

---

## Logging Standards

- **Backend:** Structured logging with bracketed prefixes indicating subsystem:
  - `[SPAN_DETECTION]` — Bias span identification
  - `[INGESTION]` — RSS feed fetching and article parsing
  - `[CLASSIFY]` — Article classification
  - `[NEUTRALIZE]` — LLM neutralization calls
  - `[BRIEF]` — Brief generation
- **Frontend:** All `console.log` calls must be wrapped in `__DEV__` guards so they are stripped from production builds

---

## Code Review Checklist

Before approving a PR, verify:

- [ ] Follows existing patterns and conventions in the surrounding code
- [ ] No security vulnerabilities introduced
- [ ] Tests cover new functionality
- [ ] No unnecessary complexity
- [ ] Documentation updated if public behavior changed
- [ ] Dark mode support verified (for any frontend UI changes)
