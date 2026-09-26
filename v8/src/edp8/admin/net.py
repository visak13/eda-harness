"""The one outbound HTTP seam for the admin panels (Slack, Plane, Tailscale, npm, test pings): every call
goes through :func:`client`, and tests set :data:`transport` to an ``httpx.MockTransport``."""

from __future__ import annotations

import httpx

#: tests replace it with httpx.MockTransport(handler); None = the real network
transport: httpx.BaseTransport | None = None


def client(timeout: float = 15.0) -> httpx.Client:
    return httpx.Client(timeout=timeout, transport=transport, follow_redirects=False)
