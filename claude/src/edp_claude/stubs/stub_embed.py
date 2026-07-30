"""StubEmbed — deterministic, offline embedding for tests + the default
context. Hashing-trick bag-of-words: each token is hashed to a fixed
index and accumulated, then L2-normalized. Not semantic, but token
overlap → higher cosine, so retrieval tests are deterministic and
meaningful (a query sharing a neuron's description tokens ranks it
top) without any network/model dependency.
"""

import hashlib
import math
import re

from ..ports import EmbedPort

_DIM = 256
_TOKEN = re.compile(r"[a-z0-9]+")


class StubEmbed(EmbedPort):
    def __init__(self, dim: int = _DIM):
        self.dim = dim

    async def embed(self, text: str, kind: str = "document") -> list[float]:
        # kind is ignored — token overlap is symmetric.
        vec = [0.0] * self.dim
        for tok in _TOKEN.findall(text.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            vec[h % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm:
            vec = [x / norm for x in vec]
        return vec
