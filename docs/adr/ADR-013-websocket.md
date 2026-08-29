# ADR-013 — WebSocket for real-time browser push

- **Status:** Accepted
- **Date:** 2026-06-30
- **Supersedes:** —
- **Superseded by:** —

## Context

Several first-class features require pushing events to the browser in near
real-time:

- Live detection / tracking events from the AI Engine on the operations
  dashboard.
- Queue length / wait-time updates.
- Loss-prevention and low-stock alerts.
- Notification Center inbox updates.
- Camera online / offline state transitions.

Polling the REST API (ADR-012) for these would either be too slow (poll
interval ≫ event rate) or generate excessive load. Server-Sent Events (SSE)
are one-directional; we also need the browser to send ack / subscribe
messages.

## Decision

Provide a **WebSocket gateway** as the real-time push channel.

- One endpoint: `/ws/v1` (versioned in parallel with REST).
- **Authentication** at handshake reuses the JWT access token (ADR-005 /
  `VM-AUTH-03`).
- The connection is a **multiplexed topic bus** — clients subscribe to
  topics like `camera.{id}.events`, `branch.{id}.alerts`,
  `notifications.user.{id}`. Subscriptions are **permission-checked** on
  every subscribe.
- **Backend → frontend** messages are JSON with a `type` and `payload`.
- **Frontend → backend** messages are limited to `subscribe`, `unsubscribe`,
  and `ack`.
- **Fan-out across backend instances** uses Redis pub/sub (ADR-010) so any
  event published from any instance reaches every connected client.
- **Reconnect + backfill**: the client receives a monotonic message ID; on
  reconnect it asks for messages since the last seen ID.
- The gateway runs in the same FastAPI process as the REST API for v1; it can
  be extracted into a separate process later without changing the contract.

## Consequences

**Positive**

- Sub-second push latency for live dashboards and alerts.
- One bidirectional channel handles every real-time concern; clients open at
  most one WebSocket per session.
- Reuses the existing auth model; no new credential type.

**Negative**

- Long-lived connections complicate load balancing — sticky sessions or
  pub/sub fan-out are required (we use Redis fan-out).
- Some corporate proxies strip WebSocket upgrade headers; we will document
  the requirement and offer SSE as a fallback only if a real customer hits
  this.

**Neutral**

- We deliberately do **not** stream high-bitrate video over WebSocket. Video
  streaming uses HLS / WebRTC (separate concerns, separate components).

## Alternatives Considered

- **Long polling** — Works behind any proxy but heavy on server resources
  and slow. Rejected.
- **Server-Sent Events (SSE)** — Simpler than WebSocket but one-directional.
  Adequate for some use cases; we may add it as a fallback channel.
- **MQTT directly to browsers** — MQTT-over-WebSocket is fine for IoT
  (ADR-014 ecosystem), but it leaks broker concerns into the browser. The
  backend will bridge MQTT → WebSocket internally.
- **Per-feature transport choices** — Mixing SSE + WebSocket + polling per
  feature would multiply complexity. Rejected for v1.
