# strategy_hl: walking-skeleton

**Intent + why.** A thin, end-to-end path through every layer of a new system proves the
architecture actually connects before any layer is built out — catching integration
mismatches when they are cheap to fix, not after each layer is polished in isolation.

**When it applies.** feature work introducing a new component/service with multiple layers
(e.g. new UI + new API + new store) where no working end-to-end path exists yet.

**Phases**
1. Skeleton — the thinnest possible real path through every layer (a hardcoded value all
   the way from UI to store and back counts), wired for real, not mocked at the boundary
   you're trying to prove.
2. Confirm the seams — each interface the skeleton crosses is the real one you intend to
   keep, not a stand-in that will be replaced.
3. Flesh out — build each layer's real behavior against the proven skeleton, one layer or
   slice at a time, keeping the path runnable throughout.

**Exit condition.** The full path works end-to-end with real (not placeholder) behavior at
every layer, and the story's criteria pass against it.

**Typical gates.** /demo the skeleton to the owner as soon as it walks, before fleshing out
— cheapest point to redirect if the shape is wrong.
