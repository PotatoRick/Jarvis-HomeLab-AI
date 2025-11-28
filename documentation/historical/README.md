# Historical Documentation Archive

This directory contains historical documentation from the development and troubleshooting of Jarvis (AI Remediation Service).

These documents are preserved for reference but have been superseded by the current documentation in the root directory.

---

## Current Documentation (Root Directory)

**Use these for up-to-date information:**

- **[README.md](../../README.md)** - Main documentation with quick start guide
- **[ARCHITECTURE.md](../../ARCHITECTURE.md)** - System design and component details
- **[CONFIGURATION.md](../../CONFIGURATION.md)** - Complete configuration reference
- **[TROUBLESHOOTING.md](../../TROUBLESHOOTING.md)** - Common issues and solutions
- **[COST-OPTIMIZATION.md](../../COST-OPTIMIZATION.md)** - Claude API cost analysis
- **[DEPLOYMENT.md](../../DEPLOYMENT.md)** - Production deployment guide

---

## Historical Files

### Major Upgrade Documentation (Nov 11, 2025)

**AI_REMEDIATION_FIXES_IMPLEMENTED_20251111.md**
- Summary of all fixes from November 11, 2025 session
- SSH connection pooling, blacklist-only validation, service rename
- Container-specific tracking, diagnostic filtering
- Now integrated into current documentation

**SSH_CONNECTION_POOLING_FIX_20251111.md**
- Detailed analysis of SSH connection pooling implementation
- 96% performance improvement (1 connection + reuses vs 24 new)
- Covered in [ARCHITECTURE.md](../../ARCHITECTURE.md#ssh-connection-pooling)

**COMMAND_WHITELIST_UPDATE_20251111.md**
- Command validation pattern updates
- Transition from whitelist to blacklist-only approach
- Covered in [ARCHITECTURE.md](../../ARCHITECTURE.md#command-validation)

**MONITORING_AUDIT_REPORT_20251111.md**
- Pre-upgrade audit of monitoring stack
- Issues identified and resolved
- Historical context for current configuration

**TROUBLESHOOTING_SSH_FIXES_20251111.md**
- SSH-related troubleshooting steps from development
- Lessons learned integrated into [TROUBLESHOOTING.md](../../TROUBLESHOOTING.md)

### Initial Development Documentation (Nov 9-10, 2025)

**AI_REMEDIATION_STALE_DATA_FIXES.md**
- Stale attempt data issues and solutions
- Container-specific instance tracking implementation
- 2-hour attempt window rationale

**AI_REMEDIATION_SKYNET_MIGRATION_COMPLETE.md**
- Migration from Outpost to Skynet deployment
- Network configuration and SSH setup
- Covered in [DEPLOYMENT.md](../../DEPLOYMENT.md)

**PROJECT_SUMMARY.md**
- Initial project overview and goals
- Replaced by current [README.md](../../README.md)

**QUICKSTART.md**
- Original quick start guide
- Superseded by [README.md](../../README.md) quick start section

**ai-remediation-system.md**
- Original system design document (38KB)
- Replaced by [ARCHITECTURE.md](../../ARCHITECTURE.md)

**ai-remediation-system-index.md**
- Index/table of contents for original system doc
- No longer needed with new documentation structure

**ai-remediation-quickstart.md**
- Duplicate quick start guide
- Consolidated into [README.md](../../README.md)

**ai-remediation-deployment-checklist.md**
- Original deployment checklist
- Expanded into [DEPLOYMENT.md](../../DEPLOYMENT.md)

**ai-remediation-docker-ssh-issue.md**
- Docker SSH connectivity troubleshooting
- Integrated into [TROUBLESHOOTING.md](../../TROUBLESHOOTING.md#ssh-connection-failures)

**ai-remediation-troubleshooting-log.md**
- Development troubleshooting notes
- Formalized into [TROUBLESHOOTING.md](../../TROUBLESHOOTING.md)

---

## Why Archive These Files?

1. **Cleaner Project Structure**
   - Root directory now contains only current, authoritative documentation
   - Easier for new users to find relevant information

2. **Historical Reference**
   - Preserved for understanding design decisions
   - Useful for debugging similar issues in the future
   - Documents evolution of the system

3. **Avoid Confusion**
   - Prevents users from reading outdated information
   - Clear separation between current and historical docs

---

## When to Reference Historical Docs

- **Researching past issues** - Detailed troubleshooting logs
- **Understanding design evolution** - Why certain decisions were made
- **Similar problem patterns** - How previous issues were resolved
- **Performance baselines** - Before/after comparisons

---

## Documentation Updates (Nov 11, 2025)

### What Changed

**Old structure:**
- 20+ documentation files in root directory
- Mix of current and historical information
- Unclear which documents were authoritative
- Duplicate content across multiple files

**New structure:**
- 6 core documentation files in root
- Historical files archived in `documentation/historical/`
- Clear, comprehensive, non-overlapping content
- Single source of truth for each topic

### New Documentation Highlights

1. **README.md** - Complete overview, quick start, and feature list
2. **ARCHITECTURE.md** - Deep dive into system design, components, and data flow
3. **CONFIGURATION.md** - Every environment variable, setting, and option documented
4. **TROUBLESHOOTING.md** - Comprehensive solutions for common issues
5. **COST-OPTIMIZATION.md** - Claude API cost analysis and optimization strategies
6. **DEPLOYMENT.md** - Step-by-step production deployment guide

---

## Need More Information?

If historical docs don't answer your question:
1. Check current documentation in root directory
2. Review git commit history: `git log --all -- <filename>`
3. Search codebase: `grep -r "pattern" app/`
4. Contact: hoelscher.jordan@gmail.com

---

**Last Updated:** November 11, 2025
**Archived:** 15 historical files (240KB total)
