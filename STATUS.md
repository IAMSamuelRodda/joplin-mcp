# Project Status

> **Purpose**: Current work, active bugs, and recent changes (2-week rolling window)
> **Lifecycle**: Living (update daily/weekly during active development)

**Last Updated**: 2025-11-30
**Current Phase**: Lazy-MCP Optimization
**Version**: 0.2.0

---

## Quick Overview

| Aspect | Status | Notes |
|--------|--------|-------|
| Desktop API Integration | 🟢 | Working after bug fix |
| Server API Integration | 🔴 | Not feasible (see ADR below) |
| Claude Code Registration | 🟢 | Registered with user scope |
| Test Coverage | 🟡 | Manual testing only |
| Known Bugs | 🟢 | Critical bug fixed |

**Status Guide:** 🟢 Good | 🟡 Attention | 🔴 Critical | 🔵 In Progress

---

## Current Focus

**Completed Today (2025-11-30):**
- ✅ Optimized all 11 tool descriptions for lazy-mcp discovery
- ✅ Fixed duplicate notebook creation (now checks for existing before creating)
- ✅ Updated improving-mcps skill with lazy-mcp integration guidance

**Previous:**
- ✅ Fixed `note_count` field bug causing 500 errors
- ✅ Added `ensure_running` tool for pre-warming

**Next Up:**
- [ ] Add automated tests
- [ ] Consider CLAUDE.md and other docs

---

## Deployment Status

### Claude Code MCP Registration
- **Status**: Deployed (user scope)
- **Command**: `claude mcp add joplin -s user --env JOPLIN_TOKEN=... -- /home/samuel/repos/joplin-mcp/.venv/bin/python /home/samuel/repos/joplin-mcp/joplin_mcp.py`
- **Verification**: `claude mcp list`

---

## Known Issues

### Fixed
**Issue: 500 Internal Server Error on joplin_list_notebooks**
- **Status**: Fixed (pending Claude Code restart)
- **Symptom**: All notebook/folder operations returned 500 error
- **Root Cause**: `note_count` field doesn't exist in Joplin's sqlite schema. The API attempted `SELECT note_count FROM folders` which failed.
- **Solution**: Removed `note_count` from fields parameter in `_get_all_paginated()` call (line 403)

---

## Recent Achievements (Last 2 Weeks)

**Lazy-MCP Optimization v0.2.0** ✅
- Completed: 2025-11-30
- Front-loaded all 11 tool descriptions for truncated discovery views
- Added duplicate notebook prevention (case-insensitive title check)
- Tool descriptions now action-first, no redundant "in Joplin" phrases
- Improved create_notebook to return existing notebook if found

**Initial MCP Server Implementation** ✅
- Completed: 2025-11-26
- Full CRUD operations for notes, notebooks, tags
- Search functionality
- Markdown and JSON response formats

**Bug Fix: note_count Field** ✅
- Completed: 2025-11-26
- Removed invalid field causing sqlite errors
- Updated markdown output formatting

---

## Architecture Decision Records

### ADR-001: Desktop API Only (No Server API)
**Date:** 2025-11-26
**Status:** Accepted

**Context:** Investigated connecting MCP server directly to self-hosted Joplin Server on VPS (notes.rodda.xyz) instead of requiring local Joplin Desktop.

**Decision:** Continue using Joplin Desktop API (localhost:41184) only.

**Consequences:**
- ✅ Full REST API access (notes, notebooks, tags, search)
- ✅ Stable, documented API
- ❌ Requires Joplin Desktop running locally
- ❌ Cannot operate headlessly on server

**Alternatives Considered:**
- Joplin Server API (rejected: sync-only, no REST endpoints for note manipulation)
- joppy library server support (rejected: experimental, may break, no encryption support)
- Direct PostgreSQL access (rejected: bypasses app logic, risky)
- Joplin CLI on server (deferred: adds complexity, could revisit if headless access needed)

---

## Next Steps (Priority Order)

1. **Restart Claude Code** to reload fixed MCP server
2. **Add basic test suite** - pytest with mocked API responses
3. **Consider CLAUDE.md** - navigation hub for AI agents

---

## Future Improvements

### Remote MCP Access (mcp.joplin.rodda.xyz)
**Status:** Deferred
**Priority:** Low

Expose MCP server over HTTPS for cloud AI integration (Claude.ai, ChatGPT, etc.).

**Requirements:**
- HTTP/SSE transport layer (MCP currently uses stdio)
- Authentication layer (API keys or OAuth)
- HTTPS reverse proxy
- Wait for Claude.ai/ChatGPT to support remote MCP connections

**Architecture:**
```
mcp.joplin.rodda.xyz → Auth + HTTPS → HTTP/SSE Bridge → Joplin MCP → Joplin Desktop API
```

**Proof of Concept:** Test with Zero (pip) agent by Arc Forge first.

---

**Note**: Archive items older than 2 weeks to keep document focused.
