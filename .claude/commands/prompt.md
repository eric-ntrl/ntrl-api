# /prompt - View/Update Pipeline Prompts

## Purpose
Inspect and modify pipeline prompts (classification, neutralization, span detection) with version history.

## Arguments
- `$ARGUMENTS` - Prompt name, optionally with "versions" or "update"

Examples:
- `/prompt` - List all prompts
- `/prompt classification_system_prompt` - View specific prompt
- `/prompt classification_system_prompt versions` - Show version history
- `/prompt neutralizer_prompt update` - Update prompt (will ask for content)

## Available Prompts

| Name | Purpose |
|------|---------|
| `classification_system_prompt` | LLM classifier system prompt |
| `classification_user_prompt` | LLM classifier user prompt template |
| `neutralizer_prompt` | Article neutralization system prompt |
| `span_detection_prompt` | Manipulation span detection prompt |

## Instructions

### List All Prompts
If no arguments:
```bash
curl -s "https://api-staging-7b4d.up.railway.app/v1/admin/prompts" \
  -H "X-API-Key: staging-key-123"
```

Display as table: name, model, version, is_active, updated_at

### View Specific Prompt
If prompt name provided:
```bash
curl -s "https://api-staging-7b4d.up.railway.app/v1/admin/prompts/{name}" \
  -H "X-API-Key: staging-key-123"
```

Display: full content, version, model, last updated

### Show Version History
If "versions" flag:
```bash
curl -s "https://api-staging-7b4d.up.railway.app/v1/admin/prompts/{name}/versions" \
  -H "X-API-Key: staging-key-123"
```

Display table: version, change_source (manual/auto_optimize/rollback), change_reason, created_at

### Update Prompt
If "update" flag:
1. First show current content
2. Ask user for:
   - New content (or diff/changes to make)
   - Change reason (required)
3. Call update endpoint:
   ```bash
   curl -s -X PUT "https://api-staging-7b4d.up.railway.app/v1/admin/prompts/{name}" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: staging-key-123" \
     -d '{"content": "NEW_CONTENT", "model": "MODEL", "change_reason": "REASON"}'
   ```
4. Confirm success and show new version number
5. Offer to run `/evaluate` to test the change

### Rollback Prompt
If "rollback" flag:
```bash
curl -s -X POST "https://api-staging-7b4d.up.railway.app/v1/admin/prompts/{name}/rollback" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: staging-key-123" \
  -d '{"target_version": VERSION, "reason": "REASON"}'
```

## Notes
- After updating prompts, run `/neutralize force` or `/classify force` to test changes
- Run `/evaluate` after prompt changes to measure impact
- Prompts have version history - you can always rollback
