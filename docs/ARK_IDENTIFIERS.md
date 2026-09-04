# GenRxiv ARK Identifier System

This document describes how GenRxiv uses Archival Resource Keys (ARKs) to
provide persistent identifiers for published articles, and how the
implementation relates to the ARK standard maintained by the ARK Alliance
(https://arks.org).

## Overview

Every article published on GenRxiv is assigned an ARK — a globally unique,
persistent identifier. The ARK resolves to the article's HTML page on
genrxiv.org and supports version-specific access and multiple output formats
(PDF, Markdown, JSON-LD, BibTeX).

ARKs are registered with the Name-to-Thing (N2T) resolver at n2t.net, which
redirects requests to GenRxiv's resolver. This means an ARK cited as
`ark:NAAN/genrxiv-2026-00001` will resolve even without the genrxiv.org hostname,
via `https://n2t.net/ark:NAAN/genrxiv-2026-00001`.

## ARK anatomy

The ARK standard defines the following structure:

```
https://example.org/ark:12345/x54xz321/s3/f8.05v.tiff
\_________________/ \__/\___/ \______/\____/\_______/
              |         |    |      |      |       |
              |   ARK Label  |      | Sub-parts  Variants
              |              |      |
Name Mapping Authority (NMA) |    Assigned Name
                             |
              Name Assigning Authority Number (NAAN)
```

The key distinction is between **sub-parts** and **variants**:

- **Sub-parts** (slash-separated, e.g. `/s3/f8`) identify structural
  divisions of a complex object — chapters, sections, files in a dataset.
- **Variants** (dot-separated, e.g. `.05v.tiff`) identify a specific
  rendering or version of the object — format, version, or both combined.

GenRxiv articles are single documents with no chapters, appendices, or
sub-files. **GenRxiv has no sub-parts.** What GenRxiv has are versions and
formats, which are both **variants**.

### GenRxiv ARK structure

```
https://genrxiv.org/article/ark:99999/genrxiv-2026-00001.v3.pdf
\___________________________/ \__/\___/ \____________/ \_____/
              |                 |    |        |          |
              |           ARK Label   |         Variant
              |                      |    (version + format)
Name Mapping Authority (NMA)         |
                              Assigned Name
                             (base name)
                                      |
                              Name Assigning Authority
                              Number (NAAN)
```

| Component       | ARK term                        | GenRxiv example                 |
|-----------------|---------------------------------|---------------------------------|
| URL prefix      | Name Mapping Authority (NMA)    | `https://genrxiv.org/article/`  |
| Label           | ARK label                       | `ark:`                          |
| NAAN            | Name Assigning Authority Number | `99999` (placeholder)           |
| Base name       | Assigned Name                   | `genrxiv-2026-00001`            |
| Version variant | Variant                         | `.v3`                           |
| Format variant  | Variant                         | `.pdf`                          |

The NMA is the hostname that resolves the ARK. GenRxiv registers
`https://genrxiv.org/article/${pid}` as its resolver rule with N2T, where
`${pid}` is replaced by the full ARK string (e.g. `ark:99999/genrxiv-2026-00001`).

## Base name format

GenRxiv base names follow the pattern `genrxiv-YYYY-NNNNN`, where `YYYY` is
the four-digit publication year and `NNNNN` is a zero-padded sequential
article ID (5 digits, allowing up to 99,999 articles per year).

Examples:
- `genrxiv-2026-00001` — the first article published in 2026
- `genrxiv-2026-00002` — the second article published in 2026
- `genrxiv-2027-00001` — the first article published in 2027 (counter resets)

This is similar to arXiv's year-based identifier scheme (e.g.
`arXiv:2401.12345`). The base name uses dashes (not dots) so that ARK
variant syntax (`.v3`, `.pdf`, `.v3.pdf`) works without ambiguity.

### Base name practices (registered with N2T)

| Practice              | Adopted | Notes                                                                 |
|-----------------------|---------|-----------------------------------------------------------------------|
| No re-assignment (NR) | Yes     | Once published, an ARK-to-article association is permanent.          |
| Lowercase only (LC)   | Yes     | All letters in base names are lowercase.                              |
| Opacity (OP)          | No      | Base names include a `genrxiv-` prefix and sequential counter.        |
| Check characters (CC) | No      | No check character is generated.                                      |

The non-opaque format is a deliberate choice for human readability, similar
to arXiv's identifier scheme (e.g. `arXiv:2401.12345`). The trade-off is
that valid ARKs are guessable and the sequential number reveals submission
order — acceptable for a preprint archive where human-readable IDs are a
feature.

### No re-assignment

GenRxiv enforces ARK permanence through several mechanisms:

- **Published articles cannot be hard-deleted.** Authors can only delete
  pending or rejected submissions. Once an article is published, its ARK is
  permanent.
- **Retraction transfers the ARK.** When an author retracts a published
  article, the ARK moves to the retraction notice (a new version). The
  original is preserved as superseded. The ARK always resolves to the
  current version of record.
- **Withdrawal preserves the ARK.** When an admin withdraws an article
  (e.g. for DMCA/research integrity), the ARK continues to resolve — to a
  tombstone page. The content is no longer served, but the identifier
  remains valid. PDF, Markdown, JSON-LD, and BibTeX endpoints return
  `410 Gone`.

## Variants

GenRxiv uses dot-separated variants for both versions and formats, following
the ARK convention. Since GenRxiv articles are single documents (not complex
multi-part objects), there are no sub-parts — everything after the base name
is a variant.

### Version variants

The base ARK (e.g. `ark:NAAN/genrxiv-2026-00001`) always resolves to the
**current version**. Specific versions are accessed by appending `.vN`:

| ARK                              | Resolves to              |
|----------------------------------|--------------------------|
| `ark:NAAN/genrxiv-2026-00001`          | Current version (HTML)   |
| `ark:NAAN/genrxiv-2026-00001.v1`       | Version 1 (HTML)         |
| `ark:NAAN/genrxiv-2026-00001.v3`       | Version 3 (HTML)         |

When viewing a non-current version, GenRxiv displays a banner indicating
that a newer version exists, with a link to the current version and the
version history page.

### Format variants

Each version (or the current version) can be accessed in multiple formats
by appending a format variant:

| Extension  | Format            | Content-Type        |
|------------|-------------------|---------------------|
| (none)     | HTML (default)    | `text/html`         |
| `.pdf`     | PDF               | `application/pdf`   |
| `.md`      | Markdown source   | `text/markdown`     |
| `.jsonld`  | JSON-LD           | `application/json`  |
| `.bib`     | BibTeX references | `text/plain`        |

### Combining version and format

Version and format variants can be combined. The version comes first,
then the format:

| ARK                                  | Resolves to              |
|--------------------------------------|--------------------------|
| `ark:NAAN/genrxiv-2026-00001`              | Current version, HTML    |
| `ark:NAAN/genrxiv-2026-00001.pdf`          | Current version, PDF     |
| `ark:NAAN/genrxiv-2026-00001.v3`           | Version 3, HTML          |
| `ark:NAAN/genrxiv-2026-00001.v3.pdf`       | Version 3, PDF           |
| `ark:NAAN/genrxiv-2026-00001.v3.md`        | Version 3, Markdown      |
| `ark:NAAN/genrxiv-2026-00001.v3.jsonld`    | Version 3, JSON-LD       |
| `ark:NAAN/genrxiv-2026-00001.v3.bib`       | Version 3, BibTeX        |

### Version history

The version history page is available at:

```
https://genrxiv.org/article/ark:NAAN/genrxiv-2026-00001/versions
```

This page lists all versions of the article with their status (published,
superseded), publication dates, and links to each version.

### How versions are stored

The database stores one row per version in the `articles` table. Only the
current (published) version holds the ARK; earlier versions have `ark =
NULL`. The version chain is tracked via the `supersedes_id` column, which
points to the root article of the chain. The `version` column stores the
sequential version number (1, 2, 3, ...).

## Suffix passthrough (SPT)

GenRxiv's resolver rule registered with N2T is:

```
https://genrxiv.org/article/${pid}
```

N2T's suffix passthrough feature means that a single registered ARK
automatically supports all variant suffixes without separate registration.
For example, if `ark:NAAN/genrxiv-2026-00001` is registered with the target URL
`https://genrxiv.org/article/ark:NAAN/genrxiv-2026-00001`, then:

| Incoming to N2T                              | N2T redirects to                                                      |
|----------------------------------------------|-----------------------------------------------------------------------|
| `ark:NAAN/genrxiv-2026-00001`                      | `https://genrxiv.org/article/ark:NAAN/genrxiv-2026-00001`                   |
| `ark:NAAN/genrxiv-2026-00001.v3`                   | `https://genrxiv.org/article/ark:NAAN/genrxiv-2026-00001.v3`                |
| `ark:NAAN/genrxiv-2026-00001.v3.pdf`               | `https://genrxiv.org/article/ark:NAAN/genrxiv-2026-00001.v3.pdf`            |

No additional registrations are needed for version or format variants.

## Legacy URL formats (backwards compatibility)

GenRxiv supports several legacy URL formats alongside the current
dot-variant syntax:

### Legacy ARK format (`ark:/`)

GenRxiv originally generated ARKs with an extra slash after the colon:
`ark:/99999/genrxiv-2026-00001`. This has been corrected to the standard format
`ark:99999/genrxiv-2026-00001`. The resolver normalizes incoming ARKs by
stripping the extra slash, so both formats resolve correctly.

### Legacy slash-separated routes

Before adopting dot-variants, GenRxiv used slash-separated routes for
formats (e.g. `/pdf`, `/markdown`) and versions (e.g. `/1`). These
continue to work as backwards-compatible aliases:

| Legacy URL                                          | Equivalent dot-variant URL                           |
|-----------------------------------------------------|------------------------------------------------------|
| `.../ark:NAAN/genrxiv-2026-00001/pdf`                     | `.../ark:NAAN/genrxiv-2026-00001.pdf`                      |
| `.../ark:NAAN/genrxiv-2026-00001/markdown`                | `.../ark:NAAN/genrxiv-2026-00001.md`                       |
| `.../ark:NAAN/genrxiv-2026-00001/jsonld`                  | `.../ark:NAAN/genrxiv-2026-00001.jsonld`                   |
| `.../ark:NAAN/genrxiv-2026-00001/bibtex`                  | `.../ark:NAAN/genrxiv-2026-00001.bib`                      |
| `.../ark:NAAN/genrxiv-2026-00001/1`                       | `.../ark:NAAN/genrxiv-2026-00001.v1`                       |
| `.../ark:NAAN/genrxiv-2026-00001/1/pdf`                   | `.../ark:NAAN/genrxiv-2026-00001.v1.pdf`                   |

New citations should use the dot-variant syntax. The legacy routes exist
solely to preserve existing external links.

## Data persistence commitment

In assigning ARKs to articles, GenRxiv commits to making a best effort to
store and manage article data and core metadata such that persistent access
can be provided. Specifically:

- **Nightly backups** to Backblaze B2 with 30-day retention (database +
  article files).
- **ARK permanence:** published articles cannot be deleted; their ARKs
  persist indefinitely.
- **Withdrawal tombstones:** withdrawn articles retain valid ARKs that
  resolve to a tombstone page with the withdrawal reason.
- **Retraction preservation:** retracted articles transfer their ARK to the
  retraction notice, preserving the citation record (per COPE guidelines).
- **Machine-readable access:** all articles are available in HTML, PDF,
  Markdown, JSON-LD, and BibTeX, plus OAI-PMH 2.0 harvesting.

## Implementation reference

| Component                  | Location                                       |
|----------------------------|-------------------------------------------------|
| ARK assignment             | `api/articles.py` — `assign_ark()`              |
| ARK normalization          | `api/articles.py` — `normalize_ark()`           |
| Variant parsing            | `api/articles.py` — `parse_ark_variant()`       |
| Version-specific lookup    | `api/articles.py` — `get_article_version()`     |
| Main article route         | `api/articles.py` — `view_article()`            |
| Format handlers            | `api/articles.py` — `_serve_pdf()`, etc.        |
| Legacy slash routes        | `api/articles.py` — `download_pdf()`, etc.      |
| JSON-LD builder            | `api/articles.py` — `build_jsonld()`            |
| OAI-PMH identifiers        | `api/oai.py` — `_oai_identifier()`              |
| NAAN configuration         | `ARK_NAAN` environment variable                 |
| Default NAAN               | `99999` (placeholder for testing)               |

## NAAN registration

GenRxiv's NAAN is registered with N2T via the NAAN request form at
https://arks.org. The registration includes:

- **Resolver rule:** `https://genrxiv.org/article/${pid}`
- **Test ARK:** `genrxiv-2026-00001` (resolves to the GenRxiv founding paper)
- **Base name practices:** NR (no re-assignment), LC (lowercase only)
- **Data persistence:** Yes

To update the NAAN (e.g. when transitioning from the placeholder `99999` to
a permanent NAAN), update the `ARK_NAAN` environment variable in `.env` and
restart the API. New articles will be minted with the new NAAN. Existing
articles' ARKs can be updated in the database with a migration.
