"""HttpEmbed — EmbedPort over ollama nomic-embed-text (vision phase 2).

The neuron DB's discovery index. OFF the control-flow path: it ranks
specialists, it never decides. On any backend failure it raises; the
caller (neuron_search / create_specialization) degrades to
NeuronStore.search_text / a null embedding — the same Jaccard-floor
philosophy as resolve_recipe.

Target host is configurable; defaults to the docker-animation-ollama
container (the canonical ollama for this project — never the deprecated
evolving-deep-agent-ollama).
"""

import httpx

from ..ports import EmbedPort

_DEFAULT_MODEL = "nomic-embed-text"


class HttpEmbed(EmbedPort):
    def __init__(
        self, base_url: str, client: httpx.AsyncClient,
        model: str = _DEFAULT_MODEL,
    ):
        self.base = base_url.rstrip("/")
        self.client = client
        self.model = model

    async def embed(
        self, text: str, kind: str = "document"
    ) -> list[float]:
        # nomic-embed-text task prefixes for asymmetric retrieval
        # (verified live 2026-05-22: without them ranking is noisy).
        prefix = "search_query: " if kind == "query" else "search_document: "
        r = await self.client.post(
            f"{self.base}/api/embeddings",
            json={"model": self.model, "prompt": prefix + text},
        )
        r.raise_for_status()
        vec = r.json().get("embedding")
        if not vec:
            raise ValueError("ollama returned no embedding")
        return [float(x) for x in vec]
