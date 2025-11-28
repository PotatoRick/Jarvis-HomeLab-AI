# AI Alert Remediation Workflow - Troubleshooting Log

**Date:** November 9, 2025
**Status:** In Progress - Data Flow Issue
**Session Duration:** ~3 hours

---

## Overview

Attempting to deploy an AI-powered alert remediation system where:
1. Alertmanager sends webhooks to n8n when alerts fire
2. n8n workflow receives alert, asks Claude AI for remediation commands
3. Executes commands via SSH on Nexus
4. Logs remediation attempt to PostgreSQL database
5. Sends Discord notification on success/failure
6. After 3 failed attempts, escalates to user

## Current Status

**What Works:**
- ✅ PostgreSQL schema deployed (3 tables, 5 views, 23 safe command patterns)
- ✅ Alertmanager webhook configuration updated
- ✅ n8n credentials configured (SSH to Nexus, PostgreSQL, Discord, Anthropic API)
- ✅ Webhook receives alerts correctly
- ✅ Alert data extraction from webhook payload
- ✅ Claude AI responds with remediation suggestions
- ✅ AI response parsing (JSON extraction from markdown)
- ✅ SSH command execution on Nexus
- ✅ Merge nodes combine data streams

**What's Broken:**
- ❌ "Log to Database" node fails with "Invalid input for 'alert_name' [item 0]"
- ❌ Alert data (`alert_name`, `alert_instance`, etc.) not reaching database insert node
- ❌ n8n's "paired item" system loses connection to earlier nodes across merges

## Root Cause Analysis

The workflow has multiple merge points and branches:
```
Extract Alert Data → Check Attempt Count → Should Auto-Fix? → Ask Claude AI → Parse AI Response → Safe to Execute? → Execute on Nexus → Merge → Check Execution Result → Log to Database
                                                                    ↓ (merge input 2)
```

**The Problem:** n8n's item pairing/lineage system breaks when:
1. Data flows through multiple branches
2. Nodes try to reference earlier nodes using `$('Node Name').item.json`
3. Execution path includes merge nodes that combine separate data streams

**Specific Issues:**
- `$('Extract Alert Data')` references fail with "Paired item data unavailable"
- `$node['Node Name']` syntax not available in this n8n version (1.114.4)
- `$input.all()` loops don't find data from nodes before merge points
- Spreading objects with `...parseData` doesn't preserve nested structures

## What We've Tried (Chronologically)

### Attempt 1: Pass alert_data Through Nodes
**Approach:** Have "Parse AI Response" create `alert_data` object, spread it through subsequent nodes
**Code:** `return [{ json: { ...parseData, alert_data: $('Extract Alert Data').item.json } }]`
**Result:** ❌ `alert_data` was `{}` (empty object)
**Reason:** `$('Extract Alert Data')` reference failed

### Attempt 2: Use $input.all() to Find Alert Data
**Approach:** Loop through all inputs to find alert fields
**Code:**
```javascript
for (let item of allInputs) {
  if (item.json.alert_name) {
    alertData = { alert_name: item.json.alert_name, ... };
  }
}
```
**Result:** ❌ `alert_data` was `null`
**Reason:** Loop couldn't find alert data in inputs from merged streams

### Attempt 3: Use $node[] Syntax
**Approach:** Use n8n's `$node['Node Name']` instead of `$()`
**Code:** `const extractData = $node['Extract Alert Data'].json;`
**Result:** ❌ Still got empty `alert_data: {}`
**Reason:** Syntax not available or not working in n8n v1.114.4

### Attempt 4: Fix AI Response Field Name
**Approach:** Change from `json.response` to `json.text` (correct field for LangChain node)
**Code:** `const aiResponse = $input.first().json.text;`
**Result:** ✅ AI parsing now works! But alert_data still null

### Attempt 5: Add Merge Node Before Parse AI Response
**Approach:** Merge alert data from "Should Auto-Fix?" with AI output from "Ask Claude AI"
**Workflow:** Should Auto-Fix? (TRUE) + Ask Claude AI → Merge → Parse AI Response
**Result:** ❌ `alert_data` still null
**Reason:** `$input.all()` couldn't find alert fields in merge inputs

### Attempt 6: Explicit Input Indexing
**Approach:** Access merge inputs by index: `allInputs[0]` (AI) and `allInputs[1]` (alert)
**Code:**
```javascript
const aiOutput = allInputs[0]?.json;
const alertInput = allInputs[1]?.json;
alertData = { alert_name: alertInput.alert_name, ... };
```
**Result:** ❌ `alert_data` still null
**Reason:** Merge inputs didn't contain expected data structure

### Attempt 7: Direct Node References in Log to Database
**Approach:** Have "Log to Database" directly reference earlier nodes
**Config:** `alert_name: ={{ $('Extract Alert Data').item.json.alert_name }}`
**Result:** ❌ New error: "Paired item data for item from node 'Check Execution Result' is unavailable"
**Reason:** PostgreSQL node can't access nodes that far back in execution lineage

### Attempt 8: Add "Prepare Database Insert" Code Node
**Approach:** Intermediate node to gather all data using direct references
**Code:**
```javascript
const extractData = $('Extract Alert Data').item.json;
const attemptData = $('Check Attempt Count').item.json;
return [{ json: { alert_name: extractData.alert_name, ... } }];
```
**Result:** ❌ "Paired item data unavailable" error in the Code node itself
**Reason:** Code node also can't access earlier nodes across merges

### Current Attempt 9: Flatten Data in Check Execution Result (IN PROGRESS)
**Approach:** Have "Check Execution Result" get data from merge inputs and flatten everything
**Code:**
```javascript
const allInputs = $input.all();
// Loop through merge inputs to find alert_name, analysis, etc.
// Package everything into flat structure
return [{ json: { alert_name: alertName, ai_analysis: analysis, success: success, ... } }];
```
**Status:** Code provided, waiting for user to test

## Key Learnings

1. **n8n's Item Pairing System:** Nodes can only reliably access data from:
   - Their immediate input (`$input.first().json`)
   - Nodes in their direct execution lineage (no branches/merges in between)

2. **Merge Nodes:** Combining data streams works, but downstream nodes lose access to pre-merge nodes

3. **Cross-Node References:** `$('Node Name')` syntax fails when:
   - Too many nodes between reference and target
   - Execution path includes branches or merges
   - Item pairing/lineage is broken

4. **LangChain AI Node Output:** Uses `text` field, not `response` field

5. **Structured Output Format:** When enabled, returns JSON schema instead of actual data (misconfigured in our test)

## Workflow Architecture

```
Webhook (POST /webhook/alert-remediation)
  ↓
Respond to Webhook
  ↓
Extract Alert Data (creates: alert_name, alert_instance, severity, etc.)
  ↓
Check Attempt Count (queries PostgreSQL for retry count)
  ↓
Should Auto-Fix? (if < 3 attempts: TRUE, else: FALSE)
  ↓ TRUE                                    ↓ FALSE
Ask Claude AI                          Discord Escalate
  ↓
Merge (combines AI output + alert data)
  ↓
Parse AI Response (parses JSON from Claude)
  ↓
Safe to Execute? (if risk != 'high': TRUE, else: FALSE)
  ↓ TRUE                                    ↓ FALSE
Execute on Nexus (SSH)                 Discord High Risk
  ↓
Merge (combines SSH output + Parse AI Response)
  ↓
Check Execution Result (determines success/failure)
  ↓
❌ Log to Database ← FAILS HERE
  ↓
Was It Successful? (if success: TRUE, else: FALSE)
  ↓ TRUE                                    ↓ FALSE
Discord Success                        Should Retry?
                                            ↓
                                       Should Escalate? (if attempts >= 3)
                                            ↓ TRUE          ↓ FALSE (retry)
                                       Discord Escalate    → back to Check Attempt Count
```

## Files Modified

1. **PostgreSQL Schema:** `/home/t1/homelab/configs/postgres/ai-remediation-schema.sql`
   - 3 tables: `remediation_log`, `command_whitelist`, `escalation_history`
   - 5 views: Latest attempts, success rates, patterns
   - 23 safe command patterns seeded

2. **Alertmanager Config:** `/home/jordan/docker/home-stack/prometheus/alertmanager.yml` (on Nexus)
   - Added webhook receiver: `https://n8n.theburrow.casa/webhook/alert-remediation`
   - Basic auth: `alertmanager:ZwZ2gQkcupdwYZFXwSF0CgpLj1guHu0T`

3. **n8n Workflow:** "Alert Remediation v2" (imported via UI)
   - 20+ nodes including webhook, AI, SSH, database, Discord notifications
   - Multiple merge points causing data flow issues

4. **n8n Credentials Created:**
   - `ssh_nexus`: SSH to 192.168.0.11 (jordan@nexus) ✅
   - `postgres_finance_db`: PostgreSQL on Outpost ✅
   - `discord_homelab_alerts`: Discord webhook ✅
   - `anthropic_claude`: Claude API key ✅
   - `ssh_outpost`: Skipped (Docker networking issue)
   - `ssh_homeassistant`: Skipped (VPN routing issue from Outpost)

5. **SSH Key Converted:** `/home/t1/.ssh/keys/homelab_ed25519`
   - Converted from OpenSSH format to PEM format for n8n compatibility
   - Command: `ssh-keygen -p -f /home/t1/.ssh/keys/homelab_ed25519 -m PEM -N ""`

## Test Results

**Test Webhooks Sent:** 16 (test-final-001 through test-final-016)
**Database Entries Created:** 0
**Successful Executions:** 0 (all fail at "Log to Database")

**Sample Test Command:**
```bash
curl -X POST https://n8n.theburrow.casa/webhook/alert-remediation \
  -u "alertmanager:ZwZ2gQkcupdwYZFXwSF0CgpLj1guHu0T" \
  -H "Content-Type: application/json" \
  -d '{
    "alerts": [{
      "status": "firing",
      "labels": {
        "alertname": "TestAlert",
        "instance": "nexus",
        "severity": "warning",
        "category": "test"
      },
      "annotations": {
        "summary": "Test alert summary",
        "description": "Test alert description"
      },
      "fingerprint": "test-final-016"
    }]
  }'
```

## Next Steps (Prioritized Solutions)

### Option 1: Flatten Data in Check Execution Result (CURRENT ATTEMPT)
**Status:** Code provided, awaiting test
**Approach:** Have "Check Execution Result" extract all needed data from merge inputs and create flat structure
**Pros:** Minimal workflow changes, uses working merge inputs
**Cons:** Complex code with loops and conditionals
**Code Location:** "Check Execution Result" node
**Next Action:** User tests updated code

### Option 2: Remove Merge Nodes, Pass Data Sequentially
**Approach:** Eliminate all merge nodes, have each node explicitly pass through all required data
**Implementation:**
- "Parse AI Response" outputs: `{ ...aiData, alert_name, alert_instance, severity, ... }`
- "Safe to Execute?" passes through all fields
- "Execute on Nexus" - can't pass data through SSH node
- **Problem:** SSH node only outputs execution results, can't pass through context

### Option 3: Use Workflow Static Data
**Approach:** Store alert data in workflow's static data storage at beginning, retrieve at end
**Implementation:**
- "Extract Alert Data": Store in `$workflow.staticData.currentAlert`
- "Log to Database": Retrieve from `$workflow.staticData.currentAlert`
**Pros:** Bypasses item pairing completely
**Cons:** May not persist across execution, potential concurrency issues
**Risk:** Untested in n8n, unclear if static data is per-execution or global

### Option 4: Split Into Multiple Workflows
**Approach:** Trigger separate workflows via webhook/sub-workflow nodes
**Implementation:**
- Workflow 1: Receive alert → AI analysis → Execute SSH → Call Workflow 2
- Workflow 2: Receive via webhook with all data → Log to database → Discord notify
**Pros:** Clean separation, no complex merges
**Cons:** More complex architecture, requires webhook/HTTP nodes between workflows

### Option 5: Use HTTP Request Node to Self
**Approach:** After SSH execution, make HTTP request back to n8n webhook with full payload
**Implementation:**
- After "Execute on Nexus": HTTP Request to `/webhook/log-remediation` with JSON body containing ALL data
- New workflow triggered by this webhook, simply logs to database
**Pros:** Guaranteed data availability (sent in HTTP body)
**Cons:** Feels hacky, adds latency, more complex debugging

### Option 6: Redesign Using Execute Workflow Trigger
**Approach:** Use n8n's "Execute Workflow" node to call sub-workflows with parameters
**Implementation:**
- Main workflow: Receive alert → Pass to "Remediate" sub-workflow
- Remediate sub-workflow: AI → SSH → Return results
- Main workflow: Log results to database
**Pros:** Cleaner architecture, proper data passing via parameters
**Cons:** Requires significant refactor, need to learn Execute Workflow node

### Option 7: Store in PostgreSQL Temp Table First
**Approach:** Store alert data in PostgreSQL immediately after extraction, retrieve it later
**Implementation:**
- After "Extract Alert Data": INSERT into `temp_alert_context` table
- Before "Log to Database": SELECT from `temp_alert_context` WHERE alert_fingerprint = X
- After logging: DELETE from `temp_alert_context`
**Pros:** Database handles data persistence, no n8n item pairing issues
**Cons:** Adds database I/O, temp table management, potential orphaned records

## Recommended Next Action

**Test Option 1 first** (flatten in Check Execution Result) since:
1. Code is already written and provided
2. Minimal workflow changes required
3. Uses working merge node inputs
4. If it works, we're done in 5 minutes

**If Option 1 fails:** Move to **Option 4 (Split Workflows)** because:
1. Cleanest long-term solution
2. Easier to debug (each workflow is simpler)
3. Better separation of concerns (alert handling vs logging)
4. More maintainable for future enhancements

**Avoid:**
- Option 3 (static data) - Unclear behavior, concurrency risks
- Option 5 (HTTP to self) - Too hacky, not maintainable
- Option 7 (temp table) - Unnecessary complexity, database overhead

## Debug Commands

**Check n8n logs:**
```bash
ssh outpost 'docker logs n8n --tail 100'
```

**Check database for entries:**
```bash
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "SELECT id, alert_name, alert_instance, severity, attempt_number, ai_analysis, success, timestamp FROM remediation_log ORDER BY timestamp DESC LIMIT 3;"'
```

**Test webhook manually:**
```bash
curl -X POST https://n8n.theburrow.casa/webhook/alert-remediation \
  -u "alertmanager:PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{"alerts":[{"status":"firing","labels":{"alertname":"TestAlert","instance":"nexus","severity":"warning","category":"test"},"annotations":{"summary":"Test","description":"Test"},"fingerprint":"test-017"}]}'
```

**View n8n execution in UI:**
1. Go to https://n8n.theburrow.casa
2. Click "Executions" in left sidebar
3. Click on most recent execution
4. Click on failing node to see error details
5. Click on earlier nodes to see their output data

## Related Documentation

- **Main Documentation:** `/home/t1/homelab/documentation/ai-remediation-system.md`
- **Setup Script:** `/home/t1/homelab/scripts/ai-remediation/setup_ai_remediation.sh`
- **Database Schema:** `/home/t1/homelab/configs/postgres/ai-remediation-schema.sql`
- **Workflow JSON:** `/home/t1/homelab/configs/n8n-workflows/alert-remediation-workflow-v2.json`
- **Alertmanager Config:** `/home/jordan/docker/home-stack/prometheus/alertmanager.yml` (on Nexus)

## Contact Info

- **Claude Code Session:** This session can be resumed with context from this log
- **n8n Version:** 1.114.4 (Self Hosted)
- **PostgreSQL Version:** Running in `n8n-db` container on Outpost
- **Anthropic API Key:** Stored in n8n credentials as `anthropic_claude`

---

**Last Updated:** November 9, 2025, 10:45 PM
**Next Session:** Continue with Option 1 test, move to Option 4 if needed
