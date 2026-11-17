# Domain Model: catalog (foundation)

Status: **Proposed for review.** Date: 2026-11-17. Scope: the `catalog` context for the first slice (search, drug page, price, equivalents, change history). Layer rules are in [ARCHITECTURE.md](ARCHITECTURE.md). Everything in `domain` is plain Python with no I/O.

## Ubiquitous language

| Term | Meaning |
|---|---|
| **Product** | A registered drug product in one market, identified by its register number |
| **Register number** | The market's identifier for a product (SFDA "Register Number") |
| **Listing** | A product's presence in the source's public list. A product is **listed** or **withdrawn from the list** |
| **Snapshot** | What the source says about one product at one moment, already translated into our terms by ingestion |
| **Listed price** | The price the source publishes, with its currency and the *basis* of that currency |
| **Price point** | A listed price together with the moment it took effect and where it came from |
| **Coded value** | A source value we keep verbatim and also recognise when it is one we know (for example legal status "Prescription") |
| **Provenance** | Source, source URL or file, fetch time, snapshot id, trust level (shared kernel) |

"Authorization status" and "marketing status" are SFDA's own fields and are kept as coded values. They are **not** the same as being listed or withdrawn from the list.

## Aggregate: `Product` (root)

Identity: `ProductId(market, register_number)`.

State (all taken from the source, nothing invented):

| Part | Model | SFDA fields |
|---|---|---|
| Names | `LocalizedText(en, ar)` for trade name | Trade Name (English page and Arabic page) |
| Ingredients | `tuple[IngredientLine]`: name, strength amount (optional), strength unit (optional) | Scientific Name, Strength, Strength Unit |
| Dosage form and route | `LocalizedText` each (route optional) | Dosage Form, Route of Administration |
| Package | `Package`: size, size unit, package type, package size, all optional | Size, Size Unit, Package Type, Package Size |
| Regulatory | `CodedValue` for legal status, product control, distribution site, authorization status, marketing status; `tuple[AtcCode]` | Legal Status, Product Control, Distribution Site, Authorization Status, Marketing Status, ATC Code 1 and 2 |
| Storage | shelf life as text (its unit is not stated by the source), storage conditions as `LocalizedText` | Shelf Life, Storage Conditions |
| Parties | `tuple[Party]` manufacturers (name, country), marketing company (`Party`), agents (names) | Manufacturers, Marketing Company, Country of marketing company, Agents |
| Other | description code | Description Code |
| Price | current `ListedPrice` (optional) and `tuple[PricePoint]` history | Price |
| Lifecycle | `ListingStatus` (listed or withdrawn) with the time of the last change | derived from the list |
| Provenance | the provenance of the last applied snapshot | stamped by ingestion |

### Invariants

- A product always has a register number and a market.
- An ATC code must have a valid shape (for example `S01BA04`, or a shorter class level such as `A07CA`).
- A price is never negative and is never a float; its currency always carries a **basis**.
- Price history is append-only and ordered by effective time; the current price equals the last price point.
- A withdrawn product does not change except by being applied again, which relists it.

### Behaviour (all pure; each returns the events it caused)

| Operation | What it does | Events |
|---|---|---|
| `Product.register(snapshot, provenance, now)` | Creates the product from a snapshot | `ProductAdded` |
| `apply(snapshot, provenance, now)` | Brings the product up to date | `PriceChanged` (old and new price), `ProductDetailsChanged` (names of the fields that changed), `ProductRelisted` (if it was withdrawn) |
| `withdraw(provenance, now)` | Marks it as withdrawn from the list | `ProductWithdrawn` |

**Idempotence:** applying the same snapshot twice changes nothing and emits nothing. This is what makes a retried ingestion run safe.

## Value objects

`ProductId`, `LocalizedText`, `IngredientLine`, `Package`, `CodedValue`, `AtcCode`, `Party`, `ListedPrice`, `PricePoint`. All frozen, validated in the constructor.

`CodedValue` keeps `raw` exactly as the source wrote it and `known` when the raw text is one we recognise (for example legal status "Prescription" or "OTC"). An unrecognised value is kept, never dropped and never mapped by guess.

## Currency

The SFDA pages show a bare number. By the owner's decision (2026-11-17) prices are **SAR**, stored with the basis `OWNER_ASSUMPTION` and shown that way in the API. The shared kernel's `Currency` therefore gains a basis: `SOURCE_STATED`, `OWNER_ASSUMPTION` or `UNCONFIRMED`.

## Events

- **Domain events** (inside `catalog.domain`): `ProductAdded`, `ProductRelisted`, `ProductWithdrawn`, `PriceChanged`, `ProductDetailsChanged`.
- **Integration events** (published language, `catalog.contracts.events`): the same five, as flat versioned messages that carry what a subscriber needs and no domain objects. The application layer translates domain events into integration events and writes them to the outbox in the same transaction as the state change.

## Contracts (what other contexts may use)

- Command `ApplyCatalogChanges(snapshots, provenance)`: ingestion sends snapshots. Idempotent.
- Command `WithdrawProducts(register_numbers, provenance)`: ingestion sends products it has confirmed are gone from the list.
- `ProductSnapshot`: the flat, source-neutral description of one product (the fields above, with `None` where the source gave nothing).
- Queries (search, product page, price history, change feed) come with persistence and are added to the contracts then.

Ingestion owns the translation from SFDA's pages to `ProductSnapshot` (an anti-corruption layer): splitting combined ingredient and strength lists, parsing numbers, reading manufacturer lines. When a source value cannot be understood (for example the number of ingredient names differs from the number of strengths), it is kept as a single unresolved ingredient line with no strength rather than guessed.

## Application layer (catalog)

Ports: `ProductRepository` (`get`, `add`, `save`), `EventOutbox` (`add`), and the shared `UnitOfWork`. Handlers: `ApplyCatalogChangesHandler`, `WithdrawProductsHandler`. One unit of work per command. Persistence and the outbox table come in the infrastructure step.

## Not modelled yet (on purpose)

Ingredient canonical ids and salts, standard dosage-form terms (Q-21), pack-price semantics (price per pack or per unit is unknown), manufacturer entity resolution, safety notices (future `safety` context), LASA name similarity (future, in `search`). Each needs real analysis or a decision first.

## Open points for review

1. Is `ProductId = (market, register_number)` right, given Egypt will have its own numbers? (Proposed: yes; cross-market mapping is Phase 2.)
2. Price history inside the aggregate is fine at this size (a few changes per product). If it grows it moves to its own aggregate.
3. Is "withdrawn from the list" the right name for what we can observe, given that the list can hide a product through its pagination glitch? Withdrawal is only recorded after ingestion has confirmed it (see SFDA_SCRAPER.md).
