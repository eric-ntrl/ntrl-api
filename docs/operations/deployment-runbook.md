# NTRL Deployment Runbook

Last updated: January 2026

---

## Infrastructure Overview

| Component      | Platform             | Details                                                  |
|----------------|----------------------|----------------------------------------------------------|
| Backend API    | Railway              | Auto-deploys from `main` branch. Build ~1m30s, deploy ~20s |
| Database       | Railway PostgreSQL   | Internal connection string (auto-set by Railway)         |
| Storage        | AWS S3               | `ntrl-raw-content` bucket, `us-east-1`                   |
| Frontend       | Expo / EAS Build     | iOS and Android via `eas build`                          |
| Staging URL    | `https://api-staging-7b4d.up.railway.app` |                                   |

---

## 1. Backend Deployment (Railway Auto-Deploy)

Railway auto-deploys every push to `main`. There is no manual deploy step under normal circumstances.

### 1.1 Standard Deploy Process

1. **Push to main:**

   ```bash
   git push origin main
   ```

2. **Railway automatically builds and deploys.** Typical timing is ~1m30s for the build and ~20s for the deploy.

3. **Migrations run automatically** on deploy via the Dockerfile `CMD`.

4. **Verify the deploy:**

   ```bash
   curl "https://api-staging-7b4d.up.railway.app/v1/status" \
     -H "X-API-Key: staging-key-123" | python3 -m json.tool
   ```

> **Note:** The `code_version` field in `/v1/status` is not auto-bumped per deploy. To confirm a deploy landed, check the Railway dashboard under Deployments.

### 1.2 Environment Variables (Railway Dashboard)

All environment variables are managed through the Railway dashboard. Do not commit secrets to the repository.

| Variable                    | Description                                  |
|-----------------------------|----------------------------------------------|
| `DATABASE_URL`              | Railway PostgreSQL (auto-set by Railway)     |
| `NEUTRALIZER_PROVIDER`      | `openai`                                     |
| `OPENAI_API_KEY`            | OpenAI API key                               |
| `GOOGLE_API_KEY`            | Google/Gemini API key (fallback provider)     |
| `ANTHROPIC_API_KEY`         | Anthropic API key (optional)                 |
| `STORAGE_PROVIDER`          | `s3`                                         |
| `S3_BUCKET`                 | `ntrl-raw-content`                           |
| `S3_REGION`                 | `us-east-1`                                  |
| `AWS_ACCESS_KEY_ID`         | AWS credentials                              |
| `AWS_SECRET_ACCESS_KEY`     | AWS credentials                              |
| `ADMIN_API_KEY`             | Admin API key for protected endpoints        |
| `RAW_CONTENT_RETENTION_DAYS`| `30`                                         |
| `ENVIRONMENT`               | `staging` or `production`                    |

### 1.3 Database Migrations

Migrations run automatically on every deploy. Manual execution is only needed for debugging or one-off operations.

**Run migrations manually:**

```bash
railway run alembic upgrade head
```

**Verify there is exactly one migration head:**

```bash
railway run alembic heads
```

> **Warning:** Always set `down_revision` to the current single head when adding new migrations. The project experienced a multiple-heads crash in January 2026 that required manual resolution. Run `alembic heads` to verify only one head exists before committing a new migration.

### 1.4 Rollback Procedures

**Option A -- Railway Dashboard (preferred):**

1. Open the Railway dashboard.
2. Navigate to Deployments.
3. Click the previous successful deployment.
4. Click "Rollback".

**Option B -- Railway CLI:**

```bash
railway rollback
```

**Option C -- Database rollback (if a migration needs reverting):**

```bash
railway run alembic downgrade -1
```

After any rollback, verify the application is healthy using the status endpoint (see section 4).

---

## 2. Scheduled Pipeline (Railway Cron)

The content pipeline runs on a Railway cron schedule and does not require manual intervention under normal operation.

### 2.1 Cron Configuration

| Setting     | Value                                          |
|-------------|------------------------------------------------|
| Schedule    | `0 */4 * * *` (every 4 hours)                 |
| Endpoint    | `POST /v1/pipeline/scheduled-run`              |
| Headers     | `X-API-Key: <admin-key>`, `Content-Type: application/json` |
| Body        | `{}` (uses defaults)                           |

### 2.2 Default Pipeline Parameters

| Parameter              | Default Value |
|------------------------|---------------|
| `max_items_per_source` | 25            |
| `classify_limit`       | 200           |
| `neutralize_limit`     | 25            |
| `cutoff_hours`         | 24            |

### 2.3 What the Scheduled Run Does

Each invocation of `/v1/pipeline/scheduled-run` performs these steps in order:

1. **Ingest** -- pulls up to 25 new articles per source.
2. **Classify** -- runs LLM classification (domain + feed_category) on up to 200 pending articles.
3. **Neutralize** -- rewrites up to 25 pending articles to remove bias.
4. **Rebuild brief** -- groups articles by the 10 feed categories.
5. **Record metrics** -- creates a `PipelineRunSummary` with health metrics and alerts.

### 2.4 Trigger a Manual Pipeline Run

```bash
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/pipeline/scheduled-run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: staging-key-123" \
  -d '{}'
```

To override defaults:

```bash
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/pipeline/scheduled-run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: staging-key-123" \
  -d '{"max_items_per_source": 50, "classify_limit": 500, "neutralize_limit": 100}'
```

---

## 3. Frontend Deployment (EAS Build)

### 3.1 Local Development

```bash
cd code/ntrl-app
npm start           # Start Expo dev server
npm run ios         # iOS simulator
npm run android     # Android emulator
npm run web         # Browser
```

### 3.2 Production Builds

**Configure EAS (first time only):**

```bash
eas build:configure
```

**Build for iOS:**

```bash
eas build --platform ios --profile production
```

**Build for Android:**

```bash
eas build --platform android --profile production
```

### 3.3 App Store Submission

1. Download the completed build artifact from the Expo dashboard.
2. **iOS:** Submit via App Store Connect using Transporter or direct upload.
3. **Android:** Upload to the Google Play Console.
4. Complete all app review requirements for each platform.

---

## 4. Health Checks

### 4.1 Full Status Endpoint (Recommended)

```bash
curl "https://api-staging-7b4d.up.railway.app/v1/status" \
  -H "X-API-Key: staging-key-123" | python3 -m json.tool
```

Returns: system status, LLM config, API key presence, article counts, last pipeline runs, health metrics, and alerts.

### 4.2 Quick Health Checks (No Auth Required)

**Brief endpoint:**

```bash
curl "https://api-staging-7b4d.up.railway.app/v1/brief"
```

**Sources endpoint:**

```bash
curl "https://api-staging-7b4d.up.railway.app/v1/sources"
```

---

## 5. Post-Deploy Verification

### 5.1 After a Backend Deploy

Run through these steps after every deploy to `main`:

1. **Check status returns healthy:**

   ```bash
   curl "https://api-staging-7b4d.up.railway.app/v1/status" \
     -H "X-API-Key: staging-key-123" | python3 -m json.tool
   ```

2. **Confirm deploy on Railway dashboard** -- look for a green checkmark on the latest deployment.

3. **Trigger a test pipeline run** (optional, but recommended after significant changes):

   ```bash
   curl -X POST "https://api-staging-7b4d.up.railway.app/v1/pipeline/scheduled-run" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: staging-key-123" \
     -d '{}'
   ```

4. **Verify the brief has content:**

   ```bash
   curl "https://api-staging-7b4d.up.railway.app/v1/brief?hours=24"
   ```

### 5.2 After Prompt Changes

Prompt changes affect neutralization and classification output. Follow these additional steps:

1. **Deploy to Railway** by pushing to `main`.

2. **Re-neutralize test articles with force:**

   ```bash
   curl -X POST "https://api-staging-7b4d.up.railway.app/v1/neutralize/run" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: staging-key-123" \
     -d '{"limit": 5, "force": true}'
   ```

3. **Rebuild the brief:**

   ```bash
   curl -X POST "https://api-staging-7b4d.up.railway.app/v1/brief/run" \
     -H "X-API-Key: staging-key-123"
   ```

4. **Inspect output with the debug endpoint:**

   ```bash
   curl "https://api-staging-7b4d.up.railway.app/v1/stories/{id}/debug" \
     -H "X-API-Key: staging-key-123" | python3 -m json.tool
   ```

---

## 6. Common Operations

### 6.1 Trigger Individual Pipeline Stages

**Ingest:**

```bash
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/ingest/run" \
  -H "X-API-Key: staging-key-123"
```

**Classify (up to 200 pending):**

```bash
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/classify/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: staging-key-123" \
  -d '{"limit": 200}'
```

**Reclassify all (force):**

```bash
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/classify/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: staging-key-123" \
  -d '{"limit": 200, "force": true}'
```

**Neutralize:**

```bash
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/neutralize/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: staging-key-123" \
  -d '{"limit": 50}'
```

**Force re-neutralize specific articles:**

```bash
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/neutralize/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: staging-key-123" \
  -d '{"story_ids": ["id1", "id2"], "force": true}'
```

**Rebuild brief:**

```bash
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/brief/run" \
  -H "X-API-Key: staging-key-123"
```

### 6.2 Debug Endpoints

**Story debug info:**

```bash
curl "https://api-staging-7b4d.up.railway.app/v1/stories/{id}/debug" \
  -H "X-API-Key: staging-key-123" | python3 -m json.tool
```

**Story processing spans:**

```bash
curl "https://api-staging-7b4d.up.railway.app/v1/stories/{id}/debug/spans" \
  -H "X-API-Key: staging-key-123" | python3 -m json.tool
```

---

## 7. Rate Limits

| Scope              | Limit    |
|--------------------|----------|
| Global             | 100/min  |
| Admin endpoints    | 10/min   |
| Pipeline triggers  | 5/min    |

---

## 8. Security Checklist

- [ ] `ADMIN_API_KEY` is set in the Railway environment
- [ ] `OPENAI_API_KEY` is not exposed in code or version control
- [ ] Database is not publicly accessible (Railway internal networking only)
- [ ] S3 bucket is not publicly readable
- [ ] HTTPS is enforced (Railway default)
- [ ] CORS is restricted to configured origins
- [ ] `ENVIRONMENT` is set to `staging` or `production`

---

## 9. Before Production Checklist

- [ ] Increase `max_items_per_source` to 50 or higher
- [ ] Increase `neutralize_limit` to 100 or higher
- [ ] Review ingestion timing (currently every 4 hours via cron)
- [ ] Decide on article retention policy (`RAW_CONTENT_RETENTION_DAYS`)
- [ ] Set `ENVIRONMENT=production` in Railway
- [ ] Verify all API keys are production keys (not staging/test keys)
- [ ] Confirm rollback procedure is understood by all operators
