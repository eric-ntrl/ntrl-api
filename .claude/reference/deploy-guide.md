# Railway Deployment Guide

## MCP Tools

All tools accept an optional `service` parameter: `api` (default), `scheduler`, or `postgres`.

| Tool | Use When |
|------|----------|
| `railway_status` | Check current deploy status before/after changes |
| `railway_logs` | Debug issues, view recent output |
| `railway_deploys` | Review deployment history |
| `railway_deploy_wait` | After git push, wait for deploy to complete |
| `railway_deploy_verify` | Full verification: deploy + health check + brief check |
| `railway_env_get` | Check environment variable values |
| `railway_env_set` | Update environment variables |
| `railway_restart` | Restart service without code changes |

## When to Use

- After pushing code changes → `railway_deploy_wait` or `railway_deploy_verify`
- Debugging production issues → `railway_logs` with filter
- Before major changes → `railway_status` to confirm current state
- Environment config changes → `railway_env_get/set`
- Debugging scheduler/cron issues → `railway_logs service="scheduler"`

## Service Configuration

- **Project**: ntrl (`c63c026a-219e-4ca8-aabd-c5158e7d38df`)
- **Staging URL**: `https://api-staging-7b4d.up.railway.app`

| Service | ID | Description |
|---------|----|----|
| `api` | `52f9ba5b-48ea-4e4b-bd89-6561d1a7156a` | FastAPI backend (default) |
| `scheduler` | `2a91fbe8-26ca-4265-b15c-e1c0fd7a1121` | Cron job runner |
| `postgres` | `2b5cf58a-dc22-4fd0-89a7-0fbdab3861d2` | Database |

## Post-Push Verification

After merging to `main` in ntrl-api:
1. Use `railway_deploy_verify` MCP tool, OR
2. CI `deploy-verify.yml` workflow runs automatically

## MCP Gotchas

- `railway_env_set` / `railway_env_get` sometimes returns 400 — use `railway variables set` CLI as fallback
- Railway CLI: `railway variables set VAR="value" --service <service-id>`
