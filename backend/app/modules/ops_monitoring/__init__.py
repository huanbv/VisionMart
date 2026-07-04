"""Operational Monitoring proxy — additive module.

This module does not implement any monitoring logic itself (see the
standalone `monitoring/` package at the repo root for that). It is a thin,
read-only, authenticated forwarding layer so the existing frontend app can
reach the monitoring service through the SAME staff login the rest of the
app already uses, without ever exposing the monitoring service's own
static API token to the browser.

Nothing in this module touches the Shopping Cart, Checkout, Payment,
Event Bus, or AI pipeline code, and it makes no writes of its own — every
endpoint here is a GET that forwards to `monitoring`'s GET endpoints and
relays the JSON response back unchanged.
"""

from __future__ import annotations
