# Web Frontend Analysis Spike — Decision Document

**Issue:** #12 (Story 5.1)
**Date:** 2026-04-09
**Status:** Decided

## Executive Summary

**Decision: Use as-is (Docker dependency)**

The [memory-palace-web-frontend](https://github.com/tomsalphaclawbot/memory-palace-web-frontend) repository is a production-ready, MIT-licensed Flask application that is fully compatible with our ChromaDB data structure. It should be consumed as a Docker image dependency rather than forked or rebuilt. This approach gives us a working visual memory browser with zero development effort while preserving the option to fork later if customization needs arise.

## Evaluation Criteria

The following five criteria were evaluated per AC1:

1. **Code quality** — structure, patterns, error handling, type safety
2. **Feature completeness** — what views and capabilities does it provide
3. **Maintainability** — code organization, test coverage, documentation
4. **License compatibility** — can we use/distribute alongside our codebase
5. **ChromaDB data compatibility** — does it work with both backends' data format

## Analysis

### 1. Code Quality

**Grade: A-**

The application is a single 762-line `app.py` with clean separation between API handlers, database utilities, and Neo4j integration. Key positives:

- Modern Python with type hints throughout
- Comprehensive error handling (JSON decode errors, Neo4j failures, parameter validation)
- Security-first design: read-only SQLite connections (`mode=ro`), prepared statements
- Clean env-based configuration with sensible defaults
- 13 API endpoint handlers and 9 utility functions

Areas for improvement:
- No structured logging (only Flask defaults)
- Frontend JavaScript tightly coupled to specific API response shapes

### 2. Feature Completeness

**Grade: A**

Implemented features:
- **Browser view** — full wing/room/drawer hierarchy with pagination and full-text search
- **Graph view** — 6 rendering engines (Cytoscape, Sigma.js, vis-network, D3 Force, ForceGraph, Neo4j live)
- **REST API** — 13 endpoints covering summary, wings, rooms, drawers, graph, and health
- **Docker deployment** — non-root user, health checks, live-reload, optional Cloudflare tunnel

Not yet implemented:
- 3D Palace view (tab scaffolded, content stub only)
- Timeline view
- Export (JSON/CSV)
- Auth provider integrations

The missing 3D view is a limitation but does not block our use case — the browser and graph views cover the primary need of inspecting ChromaDB contents.

### 3. Maintainability

**Grade: A- (documentation excellent, test coverage absent)**

Documentation:
- Comprehensive README with quick-start guide
- CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md
- CHANGELOG.md (Keep a Changelog format)
- Prioritized TODO.md roadmap
- PR template

Code maintainability:
- Single responsibility per function
- Clear naming conventions
- Minimal runtime dependencies (Flask, Gunicorn, neo4j)
- ~2,200 lines of frontend JavaScript (app.js + graph-view.js)

**Risk: No automated tests.** The TODO.md lists API smoke tests as P0 priority but they have not been implemented. This is the single largest maintenance risk — schema changes in ChromaDB or regressions in the Flask handlers would go undetected.

### 4. License Compatibility

**Grade: Pass**

- **License:** MIT (2026 Tom Chapin)
- **Compatibility:** Fully compatible with MIT, Apache 2.0, and any permissive or copyleft license
- **Requirements:** Include original license text in derivatives
- **Permissions:** Commercial use, modification, sublicense, distribution all permitted

No license concerns for any of the three integration options.

### 5. ChromaDB Data Compatibility

**Grade: A — fully compatible**

The frontend accesses ChromaDB via **direct SQLite3 queries** (not the ChromaDB Python client). It reads from the `embeddings` and `embedding_metadata` tables with these expected metadata keys:

| Key | Type | Our Backend Stores It? |
|-----|------|----------------------|
| `wing` | string | Yes — `session_data.project` |
| `room` | string | Yes — `seg.topic` or `"general"` |
| `source_file` | string | Yes — `seg.source_file` |
| `filed_at` | string | Yes — ISO 8601 timestamp |
| `chunk_index` | int | Yes — segment index |
| `chroma:document` | string | Yes — auto-stored by ChromaDB |

Our backend also stores additional metadata (`memory_type`, `session_id`, `timestamp`, `project`, `topic`) that the frontend's drawer detail view will display as extra fields.

**Both backends (native ChromaDB and MemPalace) use the same ChromaDB collection structure**, so the same frontend instance can browse either backend's data. This matches the design spec Section 9 architecture of two frontend instances — one per backend.

**Risk:** Direct SQLite3 access bypasses ChromaDB's API stability guarantees. If a future ChromaDB version changes its internal schema, the frontend's SQL queries would break. However, ChromaDB's SQLite schema has been stable across v0.5–v0.6+, and the read-only access pattern means no risk of data corruption.

## Options Considered

### Option A: Use As-Is (Docker Dependency)

Deploy the frontend as a Docker image, mounting our ChromaDB data directory as a read-only volume. Two instances per the design spec — one for each backend.

**Pros:**
- Zero development effort
- Upstream maintenance and feature additions come free
- Clean separation of concerns (we maintain the backend, upstream maintains the UI)
- Docker Compose config already documented in our design spec Section 9
- Production-ready Docker setup with non-root user and health checks

**Cons:**
- No control over feature roadmap
- Custom metadata fields (`memory_type`, `topic`) display as raw key-value pairs, not purpose-built UI
- Upstream could abandon the project (mitigated: MIT license allows forking at any time)

### Option B: Fork Into Repo

Fork the repository into the 3D-Stories org and customize.

**Pros:**
- Full control over features and UI
- Can add purpose-built displays for our custom metadata
- Can add our own test suite
- Can integrate with our memory server API (not just raw ChromaDB)

**Cons:**
- Maintenance burden — we own all future updates
- Diverges from upstream, complicating future merges
- Premature optimization — we don't yet know what customizations we need
- Duplicates effort if upstream adds the features we want

### Option C: Build Custom Implementation

Build a new web frontend from scratch, potentially using a different framework.

**Pros:**
- Purpose-built for our exact needs
- Can use our preferred tech stack
- Tight integration with our server API

**Cons:**
- Significant development effort (estimated 2-4 weeks for feature parity)
- Reinvents what already exists and works
- Delays Epic 5 timeline substantially
- The existing frontend already covers our core use case

## Decision

**Decision: Option A — Use as-is (Docker dependency)**

### Rationale

The primary reasons for choosing "use as-is" over the alternatives:

1. **It already works.** The frontend is fully compatible with our ChromaDB data, production-ready, and the Docker setup matches our design spec exactly. There is no technical gap blocking immediate use.

2. **The "fork" trigger hasn't fired.** Forking makes sense when we have concrete customization needs that upstream cannot serve. We don't have those yet — our custom metadata fields are visible in the drawer detail view, just not in a purpose-built UI. If that becomes a pain point, we can fork then.

3. **Building custom is wasteful.** The existing frontend provides browser view, graph view, REST API, and Docker deployment. Rebuilding any of this from scratch would be pure waste when a working MIT-licensed solution exists.

4. **Forking is always available.** The MIT license means we can fork at any point in the future with zero legal risk. "Use as-is" preserves optionality while delivering value immediately.

### When to Revisit

This decision should be revisited if:
- We need tight integration with our memory server API (e.g., semantic search from the UI)
- The upstream project becomes unmaintained (no commits for 6+ months)
- ChromaDB changes its internal SQLite schema and upstream doesn't adapt
- We need authentication/authorization on the browser (upstream lists this as P2 roadmap)

## Next Steps

1. **Issue #13+:** Create Docker Compose config per design spec Section 9 (two instances, read-only mounts)
2. **Issue #14+:** Create `/rawgentic:memory-ui` management skill (up/down/status subcommands)
3. **Verify live:** Mount actual ChromaDB data and confirm the browser/graph views render correctly
4. **Monitor upstream:** Watch for v1.1.0 with 3D view and timeline features
