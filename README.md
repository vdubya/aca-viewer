# Specs SaaS Editor (JavaScript + Lexical)

This repository now provides a **full JavaScript implementation** of a SpecsIntact-style SaaS specification editor using **React + Lexical**.

## Features

- Multi-tenant organizations, users, and role-aware behavior (`admin`, `editor`, `reviewer`)
- Project + section management
- Rich text section editing powered by Lexical
- Section status/discipline metadata
- Revision history with version snapshots and line-level diff
- Reusable clause library and one-click clause insertion
- Submittal register generation from section content
- Rule-based drafting assistant recommendations
- Admin dashboard with metrics and audit log
- Browser-persistent storage via `localStorage`

## Run locally

```bash
npm install
npm run dev
```

Then open `http://localhost:5173`.

## Build

```bash
npm run build
```

## Notes

- This is a production-style UI/workflow prototype with local browser persistence.
- For production SaaS deployment, wire this UI to a secure JavaScript backend (auth, database, API, audit retention, and RBAC enforcement).
