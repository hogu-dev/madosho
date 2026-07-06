# Component origin and licensing

madosho is built to run and compare ANY RAG component -- that is the point of
the project, and nothing in it restricts what you can install or select. What
madosho adds for deployments that have procurement rules (government and
government-adjacent customers especially) is transparency: every component
carries factual origin and license metadata, and the default install is
packaged so that checking a common rule is easy instead of an audit project.

What this page is not: legal advice or a certification. madosho publishes
facts about its components and links to the rules themselves; whether a
deployment satisfies a given rule is a determination only you (and your
counsel or contracting officer) can make.

## The labels

Every component carries metadata you can inspect:

```
madosho components list
```

The output includes license, org, and origin columns. Origin is one of three
source labels:

| Origin | Meaning |
|--------|---------|
| `us_src` | Developed by a US organization, and (for models) trained from US-developed base weights. |
| `allied_src` | Org and base-weight lineage within the US/allied set below, with at least one non-US link (example: a German org's cross-encoder built on a Microsoft base). |
| `cn_oth_src` | The org or the base weights come from outside the US/allied set. China is the common case (and lineage matters: a US fine-tune of a China-developed base model is `cn_oth_src`); `org_country` and `base_lineage` name the actual country either way. |

**The US/allied set**, as this project uses the term: the United States,
EU/EEA members, the United Kingdom, Canada, Australia, New Zealand, Japan,
and South Korea. If your rule uses a different list, the per-component `org`,
`org_country`, and `base_lineage` fields hold the underlying facts, so you
can apply your own list instead of ours.

The origin value is recorded in code next to each component and served by the
`/components` API the workbench reads.

## Labels inform; they never gate

madosho core contains no license or origin enforcement. If you install the
CN/other-source bundle and build a pipeline with a China-developed embedder, madosho
does exactly what you asked -- comparing such components against everything
else is a first-class use of the tool. The labels power transparency
(`components list`, the workbench) and recommendations, nothing else.

The only boundary is packaging: which components are in the default install
versus a separate opt-in install. That boundary exists so a deployment under
origin rules can rely on "default install = US/allied-source only" without
auditing every component -- and so everyone else loses nothing.

## What ships in the default install

Every non-hidden built-in component is `us_src` or `allied_src`, and the test
suite enforces it (`tests/unit/test_origin_guard.py` fails if a component
outside that set is ever added to the default install). Code dependencies are
permissively licensed (Apache-2.0, MIT, BSD; plus LGPL psycopg used as a
dynamically-linked library -- see `NOTICE`).

Model weights never ship with the repository. Embedding and reranking models
download from Hugging Face on first use, under each model's own license, into
your local cache. The example model services (`services/`) work the same way:
no weights in the repo, none baked into images.

### OCR engines (a dependency nuance worth stating plainly)

The `docling`/`router` parsers can OCR scanned documents (`ocr: true`), with a
per-pipeline engine choice. The engines are options on a `us_src` component,
not components themselves, so their origins are recorded here:

- **tesseract** (default) -- the classic open-source engine, Apache-2.0,
  US-lineage (HP, then Google). The madosho image installs it from Debian.
- **rapidocr** -- upstream docling's own standard install ships the rapidocr
  package, and that package bundles small PP-OCR text-recognition models
  whose lineage is China-developed (PaddleOCR family) -- `cn_oth_src` facts by
  this page's vocabulary. madosho does not add these bytes; they arrive with
  docling itself, for anyone who installs it. madosho never runs them by
  default: the default engine is tesseract, and rapidocr executes only when a
  user explicitly selects it for a pipeline.
- **easyocr** -- Apache-2.0, developed by JaidedAI (Thailand); not in the
  default install (for size, not origin), opt-in via `compose.ocr.yaml`.
  Models download on first use; nothing is baked into the image.

## What installs separately, on purpose

Two component sets are packaged as separate installable bundles:

- **The CN/other-source models bundle** -- components whose models are
  `cn_oth_src` (for example BGE-family embedders/rerankers and Qwen-family
  model servers). Often top of the benchmark leaderboards; excluded from the
  default install only so that deployments with origin rules never pull them
  in by accident.
- **The AGPL bundle** -- adapters whose code dependencies are AGPL-licensed
  (for example a PyMuPDF-based parser). Isolated so the default install's
  permissive licensing stays unconditional.

Installing a bundle is an explicit opt-in. Once installed, its components
register through the same plugin mechanism as built-ins and carry the same
metadata, so `components list` shows their origin and license alongside
everything else. For organizations that need enforced policy (the reverse
concern: guaranteeing a component is never resolved), the resolution hook
seam (`madosho.core.hooks`) lets an installed package observe or veto
component resolution and emit audit records -- enforcement stays outside the
core, where a policy owner controls it.

## Mapping the labels to procurement rules

Rules in this space change quickly and are often drafts. madosho does not
claim conformance with any of them; the labels exist so you can check a
deployment against the text of whatever rule binds you.

- **"Covered nation"** (10 U.S.C. 4872(d)(2)) -- the NDAA-family term for
  China, Russia, North Korea, and Iran. A `cn_oth_src` component is not
  automatically from a covered nation (the label also covers, say, a
  neutral-country lab) -- check its `org_country`; every `cn_oth_src`
  component in madosho's own bundles today is China-developed and does fall
  within it. https://www.law.cornell.edu/uscode/text/10/4872
- **"Foreign adversary"** (15 CFR 791.4) -- a broader Commerce list (adds
  Cuba and the Maduro regime; explicitly includes Hong Kong and Macau) that
  the Secretary can expand by determination. The same org_country check
  applies here.
- **GSA draft clause GSAR 552.239-7001** ("Basic Safeguarding of Artificial
  Intelligence Systems", draft, March 2026) -- proposes requiring federal
  contractors to use "American AI Systems", defined with reference to OMB
  Memorandum M-25-22. A rule of that shape is asking for `us_src` (or,
  depending on its final definitions, `allied_src`) components. Status: draft; comment
  period closed April 2026; not in force.
  https://buy.gsa.gov/interact/system/files/GSA_Federal_Acquisition%20Service%20Proposed%20Government%20AI%20System%20Terms%20and%20Conditions.pdf

In every case, read the rule's own definitions -- the labels are inputs to
that reading, not a substitute for it.

## Known limits

- Origin labels cover madosho's built-in components and bundled model
  choices, not the full transitive Python dependency tree. A repeatable
  transitive origin/license audit is on the roadmap.
- Draft rules cited above may change or die in comment; check status before
  relying on them.
- Origin describes organizations and training lineage, not training data.
  No claim is made about the data any model was trained on.
