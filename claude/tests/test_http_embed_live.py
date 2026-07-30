"""Live ollama embedding test (vision phase 2 prod path).

Auto-SKIPS when ollama is unreachable, so the default suite stays
offline/deterministic. When the container is up (docker-animation-
ollama-1, host port 11435), it proves HttpEmbed gives *semantic*
ranking — stronger than StubEmbed's token overlap.

Run explicitly with:
  EDP_OLLAMA_URL=http://localhost:11435 pytest tests/test_http_embed_live.py
"""

import os

import httpx
import pytest

from edp_claude.clients.http_embed import HttpEmbed
from edp_claude.store.neuron_store import cosine

_URL = os.environ.get("EDP_OLLAMA_URL", "http://localhost:11435")


def _ollama_up() -> bool:
    try:
        r = httpx.get(f"{_URL}/api/tags", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _ollama_up(), reason=f"ollama not reachable at {_URL}"
)


async def test_http_embed_returns_vector():
    async with httpx.AsyncClient(timeout=30.0) as client:
        emb = HttpEmbed(_URL, client)
        v = await emb.embed("domain driven design")
        assert isinstance(v, list) and len(v) > 100
        assert all(isinstance(x, float) for x in v[:5])


async def test_http_embed_ranks_semantically():
    # Proves the prod discovery index works AND that the search_query:/
    # search_document: prefixes are load-bearing (verified 2026-05-22:
    # WITHOUT them ranking inverts — react beat java for a java query).
    # nomic margins are thin, so we assert argmax over several realistic
    # specialist descriptions rather than a single pairwise margin.
    docs = {
        "java": "Java domain-driven design with Spring Boot "
                "microservices and JPA",
        "react": "React hooks and Tailwind CSS frontend UI components",
        "python": "Python data pipelines with pandas and async FastAPI",
        "devops": "Kubernetes Docker CI CD pipelines and Terraform infra",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        emb = HttpEmbed(_URL, client)
        query = await emb.embed(
            "how do I build a spring boot backend service in java",
            kind="query",
        )
        scored = {}
        for k, v in docs.items():
            scored[k] = cosine(query, await emb.embed(v, kind="document"))
        best = max(scored, key=scored.get)
        assert best == "java", f"expected java top, got {scored}"
