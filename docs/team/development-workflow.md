# Development Workflow

Current development practices for NTRL, including git conventions, local setup, testing, and staging.

---

## Git Workflow

### Branch Naming

Use descriptive branch names with the following prefixes:

- `feature/` — New functionality
- `fix/` — Bug fixes
- `refactor/` — Code restructuring without behavior change
- `docs/` — Documentation updates

### Commit Messages

Write commit messages in imperative mood, keeping them descriptive and concise:

- "Add RSS source validation"
- "Fix brief generation for empty story list"
- "Refactor neutralizer provider interface"

For **ntrl-app**, conventional commit prefixes are also acceptable:

- `feat: add pull-to-refresh on brief screen`
- `fix: dark mode toggle not persisting`
- `docs: update component prop documentation`

### PR Process

1. Create a branch from `main`
2. Make changes and commit
3. Push the branch to origin
4. Create a PR with a clear description of what changed and why
5. Ensure all tests are passing
6. Request code review
7. Squash merge into `main`

---

## Backend Development

```bash
cd code/ntrl-api
pipenv install
pipenv run dev  # or: pipenv run uvicorn app.main:app --reload --port 8000
pipenv run pytest
pipenv run pytest --cov=app
```

---

## Frontend Development

```bash
cd code/ntrl-app
npm install
npm start
npm run ios / npm run android / npm run web
npm test / npm run test:watch / npm run test:coverage
npm run lint / npm run lint:fix / npm run format
npm run e2e  # Playwright E2E tests
```

---

## Database Migrations

```bash
pipenv run alembic revision --autogenerate -m "Description"
pipenv run alembic upgrade head
pipenv run alembic downgrade -1
```

**IMPORTANT:** Always verify a single head with `alembic heads` before committing new migrations. Multiple heads will break the migration chain and must be linearized before merging.

---

## Testing the Full Pipeline

Run each stage in order to exercise the complete article-to-brief pipeline:

1. **POST /v1/ingest/run** — Ingest articles from configured RSS sources
2. **POST /v1/classify/run** — Classify articles by topic and manipulation score (added January 2026)
3. **POST /v1/neutralize/run** — Neutralize detected bias spans in articles
4. **POST /v1/brief/run** — Build the daily brief from neutralized articles
5. **GET /v1/brief** — View the resulting brief

---

## UI Testing with Playwright (RECOMMENDED)

Playwright is the recommended approach for end-to-end testing of the frontend:

```bash
cd code/ntrl-app
npm start -- --web &
# Create capture script and run with node
npx playwright test e2e/
```

---

## Staging Environment

- **URL:** https://api-staging-7b4d.up.railway.app
- **Admin key:** staging-key-123 (passed via `X-API-Key` header)
- **Deployment:** Auto-deploys from `main` on push

---

## Cost-Efficient Testing

LLM calls cost money. Follow these practices to minimize spend during development:

1. Use the `story_ids` parameter for targeted re-neutralization instead of processing all articles
2. Test via `/debug/spans` first (no DB writes) to validate span detection changes
3. Pick 5-10 representative articles per prompt change rather than running the full corpus
4. Target high-manipulation sources to get the most signal per LLM call

---

## Environment Variables

**Backend:** `DATABASE_URL`, `NEUTRALIZER_PROVIDER`, `STORAGE_PROVIDER` (see `.env.example` for the full list)

**Frontend:** `EXPO_PUBLIC_ENV` and `src/config/index.ts` for environment-specific configuration

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Database connection fails | `brew services start postgresql` |
| Migration errors | `dropdb ntrl && createdb ntrl && pipenv run alembic upgrade head` |
| Expo issues | `expo start -c` to clear cache |
| API 500 errors | Check logs with `pipenv run dev` |
| Alembic multiple heads | Run `alembic heads` to confirm, then linearize the chain |
