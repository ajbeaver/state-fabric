# State Fabric

State Fabric is an experiment in distributed authenticated state.

The core question is simple:

> Can authenticated Ethereum state be distributed across many heterogeneous peers, reconstructed from only a subset of them, repaired after failures, and independently verified against canonical chain state without requiring every participant to store the entire state database?

The project is intentionally not trying to replace Ethereum consensus, define canonical truth, or build a new execution engine.

Ethereum decides what state is canonical.

State Fabric explores how that state, and the authenticated structure required to prove it, could be made available across a distributed storage fabric.

---

## The problem

Ethereum state is globally committed, but the practical burden of storing, serving, and maintaining that state is concentrated in relatively capable machines.

That creates a tension.

Ethereum wants broad verification and decentralization, but maintaining full execution state locally has non-trivial storage, I/O, bandwidth, and operational costs.

The original State Fabric experiment started from a simple question:

> What if participants did not each need the whole state?

Instead, a large authenticated state could be broken into independently verifiable pieces and distributed across many machines with very different capabilities.

A peer might contribute a few megabytes.

Another might contribute hundreds of gigabytes.

No individual participant would necessarily hold the complete state.

The network as a whole would.

The important requirement is that this cannot become a trusted distributed database.

A peer saying "I have Alice's state" is not enough.

The recovered data must remain independently verifiable against Ethereum's canonical state commitments.

That distinction drives most of the architecture.

---

## Core separation of responsibilities

State Fabric currently treats three questions as fundamentally separate:

### What is true?

Ethereum or another external canonical source answers this.

For the simulator, that source is currently a deterministic local canonical history.

In Phase 3, it should become Anvil and eventually real Ethereum block/state commitments.

Storage availability must never determine canonical truth.

A state object does not become canonical because many peers store it.

A stale state object does not become current because it has better redundancy.

Canonical ordering and canonical roots come from outside State Fabric.

### What data exists?

Content addressing answers this.

Objects are identified by the bytes they contain.

If the bytes change, the object identity changes.

If the bytes do not change, the object identity should not change merely because the rest of the world changed.

### Is the data available?

Custody and retention answer this.

Peers advertise capacity and store fragments of objects.

Objects may be reconstructable, fully protected, degraded, repairable, historical, or unavailable.

These are availability properties.

They are not truth properties.

The project tries to preserve this separation everywhere:

```text
canonical source
    decides truth

content addressing
    decides object identity

custody / retention
    decide availability
````

---

## What Phase 1 established

Phase 1 tested whether static authenticated state could survive outside the publishing peer.

The simulator creates deterministic peers with Ethereum-shaped addresses and local state.

A canonical state root is committed.

A peer's state is packaged, content-addressed, erasure-coded, and distributed to other peers.

The original publisher can then disappear entirely.

The remaining network can still reconstruct the state object from a threshold subset of fragments and independently verify it against the trusted canonical root.

The experiment currently uses a simple 2-of-5 erasure scheme.

That detail is not fundamental.

The important result is the separation between:

```text
fragment integrity
object identity
canonical validity
```

A fragment hash proves that a fragment's bytes are intact.

The object hash proves that reconstructed bytes match the original content-addressed object.

The canonical proof proves that the reconstructed state belonged to the trusted canonical state.

None of those steps requires trusting the custodian that supplied the bytes.

Phase 1 also established that custody is a claim about availability, not ownership.

A stale fragment may physically remain on disk after a custody lease expires.

That does not make it active network custody.

Likewise, publisher disappearance must not destroy network recoverability.

---

## What Phase 2 established

Phase 2 introduced time.

State can now change from one canonical state to another.

That forced the project to distinguish:

```text
valid
current
available
protected
historical
```

These are not the same thing.

A historical object can still be valid.

A current object can temporarily be under-protected.

A reconstructable object may still fail the configured protection target.

A highly available old object must not be mistaken for current state.

The simulator now models repeated transitions:

```text
root N
state change
root N+1
state change
root N+2
```

Old and new objects coexist as separate immutable objects.

Canonical ordering comes from the canonical source rather than from storage health.

---

## Reconstructable is not the same as protected

This became an important distinction during transition-failure testing.

With the current 2-of-5 encoding:

```text
2 valid fragments
= reconstructable
```

but that does not mean the object satisfies the desired protection policy.

The current toy protection target is effectively the full configured fragment set.

So an object may be:

```text
canonical current
reconstructable
under-protected
```

at the same time.

This matters during transitions.

An older safe version must not be retired simply because a newer version barely crosses the reconstruction threshold.

State Fabric instead preserves a safety window until the required newer protected window is actually healthy.

The important invariant is:

> Canonical state may advance independently of storage convergence, but State Fabric must not release the last safely protected predecessor until the required newer protection window satisfies its storage guarantees.

This means canonical progress and storage convergence are separate processes.

```text
canonical:
N -> N+1 -> N+2 -> N+3

storage:
created -> partially distributed -> reconstructable -> protected
```

The chain should not need to wait for full distributed redundancy before it can advance.

---

## Sparse state versions

Phase 2 also exposed a major assumption that only worked in the toy.

Global canonical state changes every block.

Individual accounts do not.

If Alice changes at canonical position 0 and then remains untouched while other accounts change through positions 1, 2, and 3, Alice should not gain fake new state versions at each global transition.

Her state history is sparse.

For example:

```text
Alice:

position 0 -> state X
position 4 -> state Y
```

Then at positions 1, 2, and 3:

```text
latest Alice state value = X
```

The project now distinguishes exact canonical registration from sparse per-address state resolution.

An exact lookup asks:

> Did Alice explicitly have an object registered at this canonical position?

A sparse lookup asks:

> What is Alice's latest registered state value at or before this canonical position?

Those are intentionally different questions.

---

## The state/witness problem

The Ethereum-shaped transition audit exposed the most important limitation in the original state package.

The original object bundled together:

```text
address
state value
canonical root
membership proof
```

This meant that if Bob changed and the global canonical root changed, Alice's package could change even when Alice's actual state value did not.

The proof changed.

The root changed.

Therefore the package bytes changed.

Therefore the object ID changed.

At Ethereum scale, that would imply recreating state objects for unchanged state simply because unrelated global state changed.

That is not acceptable.

The project is now separating:

```text
state value identity
canonical commitment identity
witness identity
```

These are different things.

---

## State values

A state value should be durable content.

Its identity should depend on the canonical state key/value bytes, not on the current global root or proof.

Conceptually:

```text
StateValue

state_key
value_bytes

state_value_id = hash(canonical key/value bytes)
```

If those bytes remain unchanged:

```text
state_value_id_before
==
state_value_id_after
```

even if the global canonical root changes.

If the value changes, the content ID changes.

The project is deliberately moving away from treating "one Ethereum account" as the permanent fundamental object type.

A more durable abstraction is:

```text
state key -> state value
```

because Ethereum state may include:

* account data
* contract storage
* code
* future state-tree elements

The commitment format may change over time.

The idea of authenticated key/value state is more stable than the current exact representation.

---

## Canonical commitments

Canonical commitments remain external truth.

A canonical reference may eventually include things such as:

```text
block hash
parent block hash
state root
```

The simulator currently uses a simpler local representation.

That representation is temporary.

State Fabric should not derive canonical truth from:

* peer popularity
* custody health
* object arrival time
* local filesystem order
* geographic proximity
* storage redundancy

The canonical source is replaceable.

Today:

```text
SimulatorCanonicalSource
```

Later:

```text
Anvil / Ethereum canonical source
```

The rest of the storage fabric should not need to care.

---

## Authenticated commitment structure

A state value and a canonical root are not enough to regenerate a membership proof.

A verifier also needs the authenticated structure connecting the root to that value.

Under Ethereum's current state structure, this means trie node preimages along the relevant path.

Other future commitment schemes may use different structures.

State Fabric therefore treats authenticated structure as separate durable content.

Conceptually:

```text
AuthenticatedNode

object_id
codec
raw_bytes
```

The storage layer should treat those bytes as opaque content.

It should not need to understand:

* Merkle sibling directions
* trie branches
* MPT nibbles
* binary-tree stems
* future Ethereum commitment formats

Interpretation belongs to a commitment backend.

The critical availability invariant is:

> For every canonical root State Fabric claims remains independently verifiable, enough authenticated structure must remain recoverable to traverse that root to the relevant state values.

This does not require duplicating an entire state tree for every block.

Authenticated structures are naturally content-addressed and structurally shared.

If most of the state does not change, most of the underlying authenticated structure can remain identical across roots.

Only affected paths need new structure.

---

## Witnesses

Witnesses are derived artifacts.

They are not durable canonical state.

A witness proves that specific state content belongs to a specific canonical commitment.

Conceptually:

```text
Witness

canonical reference
state references
proof material
```

A verifier combines:

```text
trusted canonical root
+
state values
+
witness
```

and verifies the cryptographic relationship between them.

The witness must not be mix-and-matchable.

These combinations must fail:

```text
state X + witness for state Y

state X + witness for root N
checked against root N+4

tampered state + otherwise valid witness

missing or tampered authenticated structure
during witness regeneration
```

The important invariant is:

> A witness proves a relationship between specific state content and a specific canonical commitment. It does not define the identity of either one.

---

## Witnesses should be regenerable

The current direction is that witnesses should not need permanent storage.

If all cached witness data disappears, independent verification should still be possible.

Given:

```text
trusted canonical root
authenticated commitment structure
state values
```

State Fabric should be able to regenerate the requested membership proof.

That means a witness is closer to a query result than a permanent object.

Conceptually:

```text
request:
    root R
    keys K1, K2, K3

fabric retrieves:
    required authenticated nodes
    required state values

commitment backend produces:
    Witness(R, K1, K2, K3)
```

The witness can then be used to verify or execute the relevant transition.

Losing the witness should be inconvenient, not catastrophic.

This is an important resilience goal.

It avoids making some privileged full-state executor the only entity capable of producing verification material.

The network should collectively retain enough authenticated state to regenerate that material.

---

## Touched state, not the whole world

A transition witness should cover state accessed by the transition.

It should not require reproducing the entire world state.

There are three useful categories:

```text
untouched state

read but unchanged state

changed state
```

Untouched state does not need new transition material.

Read-but-unchanged state may still need to be supplied and proven because execution depended on it.

Changed state requires authenticated pre-state plus a resulting new state value.

The working model is:

```text
existing state remains current by default

only touched state participates in transition verification

only changed state produces new durable state values
```

This avoids treating every global root change as if every state value changed.

---

## Commitment backends

State Fabric should not permanently depend on one Ethereum commitment scheme.

The project therefore needs a replaceable commitment backend boundary.

Conceptually:

```text
CommitmentBackend

commit(...)
build_witness(...)
verify_witness(...)
```

The exact interface may evolve, but the responsibility boundary matters more than the names.

The current toy Merkle implementation should become one backend.

Later, Phase 3 can introduce an Ethereum-specific backend.

If Ethereum changes its authenticated state structure again in the future, State Fabric should replace the backend rather than rewrite:

* custody
* repair
* retention
* content addressing
* distribution

The intended replacement model is:

```text
SimulatorCanonicalSource
        ->
EthereumCanonicalSource


ToyMerkleBackend
        ->
EthereumCommitmentBackend
```

State Fabric's storage layer should remain mostly unchanged.

---

## Storage and custody

Storage should answer only:

> Do we have these exact bytes, and can we make them available?

It should not decide whether those bytes are canonical Ethereum state.

The storage layer should deal in generic content-addressed objects.

Conceptually:

```text
object_id
object_type
bytes
size
content hash
custody information
```

Possible object types may include:

```text
state-value
authenticated-node
```

and later other categories.

Custody should not parse the internal cryptographic meaning of those objects.

Its responsibility is byte-level integrity and availability.

The commitment backend handles cryptographic interpretation.

The canonical source handles truth.

This boundary is fundamental.

---

## Historical state

Historical state is not equivalent to deleted state.

When an object leaves mandatory hot protection, its bytes may remain.

Its canonical validity does not disappear.

Its repair obligation may disappear.

Phase 2 currently distinguishes:

```text
current
fallback
historical
```

Current and fallback objects are protected according to the active retention policy.

Historical objects may remain reconstructable but no longer trigger automatic repair.

The long-term historical storage model is intentionally unresolved.

Keeping every tiny historical object permanently under independent high-redundancy custody would eventually create excessive:

* storage overhead
* metadata overhead
* repair traffic
* discovery traffic

A later Phase 2+ problem is likely to involve aggregating historical content into larger archival units with different redundancy and latency expectations.

That has not been designed yet.

---

## What State Fabric is not trying to do

State Fabric is not currently attempting to:

* replace Ethereum consensus
* decide canonical state
* build a new blockchain
* modify EVM semantics
* require Ethereum clients to adopt the simulator's data model
* force every peer to store the whole state
* make custody metadata authoritative
* use popularity or geography to determine truth
* permanently commit to the current Ethereum trie format
* permanently store every generated witness
* solve production networking yet
* solve public-testnet operation yet

The project is currently testing whether the underlying distributed-state model is sound enough to justify those later steps.

---

## Current project phases

### Phase 1 — Distributed Static State

Proved that authenticated state can be:

* content-addressed
* erasure-coded
* distributed to independent peers
* reconstructed after publisher loss
* verified against canonical state
* repaired after fragment loss

### Phase 2 — Dynamic State

Proved:

* repeated canonical state transitions
* immutable historical versions
* canonical ordering independent of custody
* sparse per-address state versions
* current/fallback/historical retention
* reconstructable vs protected distinction
* publisher-independent recovery
* transition safety under partial distribution
* protection through corruption and failed repair
* canonical progress independent from storage convergence

Phase 2 deliberately ended before redesigning the state/witness object model.

### Phase 2+ — Chain-Scale State Architecture

Current phase.

The purpose is to break assumptions that work in the simulator but would fail at Ethereum scale.

Current areas include:

* separating state identity from canonical witnesses
* retaining authenticated structure required for proof regeneration
* regenerating witnesses from distributed state
* making the commitment scheme replaceable
* asynchronous canonical progress vs storage convergence
* chain-scale ingestion measurement
* execution-facing hot-state/cache behavior
* scalable custody discovery
* historical state aggregation

### Phase 3 — Anvil Integration

The goal is to replace simulator-specific canonical and commitment sources with a real local Ethereum execution environment.

Phase 3 should ideally replace adapters rather than redesign the entire fabric.

### Phase 4 — Public Testnet

The goal is to observe externally driven Ethereum state and characterize whether the architecture remains practical under real network activity.

---

## Current invariants

These are the rules the architecture should not violate without an explicit design change.

**Canonical truth is external.**

Storage availability never decides what state is canonical.

**Content identity comes from bytes.**

Availability metadata does not define object identity.

**State-value identity is independent of global root changes.**

If the state key/value bytes do not change, the state-value ID should not change.

**Canonical commitment identity and state identity are separate.**

A state value does not contain its canonical truth.

**Witnesses are derived.**

A witness is evidence connecting state to a canonical commitment.

It is not canonical state itself.

**Witness loss must not destroy independent verification.**

Retained state and authenticated structure should be sufficient to regenerate required proofs.

**Authenticated structure is part of the availability problem.**

State values alone are not enough to prove membership under a root.

**Commitment formats are replaceable.**

Storage/custody must not depend on MPT, binary-tree, or other scheme-specific semantics.

**Custody describes availability, not truth.**

A custody claim cannot make invalid bytes canonical.

**Physical bytes and active custody are different.**

Expired or stale bytes may exist without counting toward network protection.

**Reconstructable and protected are different states.**

Meeting a decoding threshold does not necessarily satisfy the configured redundancy policy.

**Canonical progress and storage convergence are asynchronous.**

The chain should not need to wait for full distributed protection before progressing.

**Sparse state histories are normal.**

An individual state key does not require a new durable object at every global canonical transition.

**Historical does not mean invalid.**

A historical state object may remain cryptographically valid and reconstructable after mandatory repair ends.

---

## Open questions

The following are deliberately unresolved.

### Witness lifetime

If witnesses are regenerable, how long should generated witness data be cached?

Possibilities include:

* fully ephemeral
* short-lived hot cache
* bounded canonical window
* optional archival retention

This should be treated as policy, not canonical truth.

### Authenticated-node retention

How long should commitment-node preimages remain protected?

Current invariant:

```text
if root R is promised as independently verifiable
then the nodes required to regenerate proofs under R
must remain recoverable
```

The efficient retention policy is not yet defined.

### Historical pruning and garbage collection

When can authenticated nodes no longer reachable from retained roots be safely released?

How should shared nodes across many historical roots be reference-counted or otherwise retained?

Not yet designed.

### Historical aggregation

Should old state values and commitment nodes eventually be packed into larger archival segments?

Likely yes, but the correct granularity and redundancy policy are unresolved.

### Witness generation at scale

How expensive is regenerating multi-key witnesses from a distributed commitment structure?

Can required nodes be fetched efficiently in parallel?

How much can common paths be shared?

This requires benchmarking.

### Execution-facing state

An executor should not perform full network reconstruction on every state read.

The eventual model probably requires:

* local hot state
* caching
* prefetching
* authenticated remote misses
* distributed durable backing

The exact boundary is not yet defined.

### Custody discovery

The current simulator replicates custody metadata directly.

That is intentionally temporary.

A chain-sized system cannot require every participant to know the complete custody map for every object.

Future work must define scalable discovery.

### Failure domains

Five fragments on five peers are not necessarily five independent failure domains.

Future protection policies may need to account for:

* geography
* provider
* network
* hardware
* administrative ownership

This is not implemented yet.

### Reorgs and finality

The simulator currently uses simple linear canonical history.

Real Ethereum can reorganize.

State Fabric interfaces should not prevent reorg-aware behavior, but actual reorg/finality handling belongs with Ethereum integration.

---

## Current experiment philosophy

The simulator is not intended to become a second Ethereum implementation.

Its purpose is to expose architectural assumptions cheaply.

When an assumption breaks, the preferred response is not to make the toy increasingly elaborate.

The preferred response is to identify the invariant, place a clean abstraction around it, and leave the Ethereum-specific implementation for the phase where Ethereum becomes the actual source.

The project should remain willing to break its own model.

A failed experiment that exposes a bad assumption is useful progress.

The intended path is:

```text
make assumption
test assumption
break assumption
identify invariant
isolate replaceable primitive
continue
```

The goal of Phase 2+ is therefore not to make the simulator look more like Ethereum.

The goal is to ensure that when Ethereum is finally introduced, the important State Fabric ideas survive the replacement of the toy.

```
