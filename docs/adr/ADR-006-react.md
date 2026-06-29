# ADR-006 — React + TypeScript + Vite for the frontend

- **Status:** Accepted
- **Date:** 2026-06-30
- **Supersedes:** —
- **Superseded by:** —

## Context

The VisionMart web UI is the primary surface for store managers, cashiers,
admins, and analysts. It must:

- Render rich, data-dense dashboards in real time.
- Stream live camera tiles (HLS / WebRTC).
- Support a long-lived WebSocket connection for live alerts.
- Be extensible by multiple frontend engineers in parallel.
- Be easy to hire for in 2026.
- Run as a static SPA behind Nginx (no SSR requirement for v1.0).

## Decision

Adopt the following frontend stack:

- **React 18** — component model, concurrent rendering for the dashboard.
- **TypeScript 5 (`strict: true`)** — type safety end-to-end with the OpenAPI
  contract (ADR-012).
- **Vite 5** — dev server with instant HMR, fast production builds.
- **TailwindCSS 3** — utility-first styling that scales across many engineers
  without bikeshedding.
- **Ant Design 5** — enterprise component library covering tables, forms,
  modals, etc. so we do not reinvent every widget.
- **React Query** for server state, **React Router** for navigation, **Zustand
  or Context** for client state (the team picks per feature).

State and data layers:

- API client is generated from the OpenAPI spec to keep the frontend honest.
- WebSocket client is a thin, typed wrapper around the native API.

## Consequences

**Positive**

- Huge talent pool; onboarding is fast.
- Type-safe client code paired with type-safe backend contracts catches
  regressions at compile time.
- Vite + Tailwind keep the developer feedback loop sub-second.
- Ant Design accelerates admin / table-heavy screens.

**Negative**

- Ant Design's design tokens differ from Tailwind's; we will establish a token
  bridge in the design-system layer.
- React 18 + Vite + AntD + Tailwind is a non-trivial dependency surface —
  upgrades require coordinated work.

**Neutral**

- We deliberately do **not** adopt Next.js (no SSR requirement and we want a
  simple static build deployable behind Nginx). Reconsider if SEO needs
  emerge.

## Alternatives Considered

- **Next.js** — Excellent, but SSR adds operational complexity we do not yet
  need. Rejected for v1.0; revisit if marketing pages or SEO matter.
- **Vue + Vuetify / Element Plus** — Equally capable. React was chosen for
  market size and the team's existing experience.
- **Svelte / SvelteKit** — Productive but smaller hiring pool. Reconsider on a
  greenfield future surface.
- **Material UI instead of Ant Design** — Comparable. Ant Design's
  enterprise-table ergonomics edged it out for our use case.
