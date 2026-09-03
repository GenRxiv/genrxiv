"""
GenRxiv API — OAI-PMH 2.0 endpoint.

Implements the Open Archives Initiative Protocol for Metadata Harvesting 2.0.
See https://www.openarchives.org/OAI/openarchivesprotocol.html

Supported verbs:
  - Identify
  - ListMetadataFormats
  - ListSets (returns noSetHierarchy error)
  - ListIdentifiers
  - ListRecords
  - GetRecord

Supported metadata prefixes:
  - oai_dc (Dublin Core)
  - oai_datacite (DataCite)
"""
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import Response

from config import config
from db import get_conn
from articles import get_article_authors

router = APIRouter()

REPOSITORY_NAME = "GenRxiv"
ADMIN_EMAIL = "admin@genrxiv.org"
GRANULARITY = "YYYY-MM-DDThh:mm:ssZ"
DELETED_RECORD = "no"
PROTOCOL_VERSION = "2.0"

METADATA_FORMATS = {
    "oai_dc": {
        "schema": "http://www.openarchives.org/OAI/2.0/oai_dc.xsd",
        "namespace": "http://www.openarchives.org/OAI/2.0/oai_dc/",
    },
    "oai_datacite": {
        "schema": "http://schema.datacite.org/meta/kernel-4/metadata.xsd",
        "namespace": "http://datacite.org/schema/kernel-4",
    },
}

PAGE_SIZE = 100


def _oai_identifier(ark: str) -> str:
    return f"oai:genrxiv.org:{ark}"


def _parse_ark_from_oai_id(oai_id: str) -> str | None:
    prefix = "oai:genrxiv.org:"
    if oai_id.startswith(prefix):
        return oai_id[len(prefix):]
    return None


def _format_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _oai_error(code: str, message: str = "") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://www.openarchives.org/OAI/2.0/ http://www.openarchives.org/OAI/2.0/OAI-PMH.xsd">
  <responseDate>{_format_date(datetime.now(timezone.utc))}</responseDate>
  <request>{config.base_url}/oai</request>
  <error code="{code}">{escape(message)}</error>
</OAI-PMH>"""


def _dc_record(article: dict, authors: list[dict]) -> str:
    """Build oai_dc metadata."""
    lines = ["<oai_dc:dc"]
    lines.append('  xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"')
    lines.append('  xmlns:dc="http://purl.org/dc/elements/1.1/"')
    lines.append('  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"')
    lines.append('  xsi:schemaLocation="http://www.openarchives.org/OAI/2.0/oai_dc/ http://www.openarchives.org/OAI/2.0/oai_dc.xsd">')
    lines.append(f"  <dc:title>{escape(article['title'])}</dc:title>")
    for a in authors:
        lines.append(f"  <dc:creator>{escape(a['name'])}</dc:creator>")
    for subj in article.get("subjects", []):
        lines.append(f"  <dc:subject>{escape(subj)}</dc:subject>")
    if article.get("abstract"):
        lines.append(f"  <dc:description>{escape(article['abstract'])}</dc:description>")
    if article.get("published_at"):
        lines.append(f"  <dc:date>{article['published_at'].strftime('%Y-%m-%d')}</dc:date>")
    lines.append("  <dc:type>Preprint</dc:type>")
    lines.append(f"  <dc:identifier>{escape(article['ark'])}</dc:identifier>")
    lines.append(f"  <dc:identifier>{config.base_url}/article/{escape(article['ark'])}</dc:identifier>")
    lines.append(f"  <dc:rights>{escape(article.get('license_url', ''))}</dc:rights>")
    lines.append("  <dc:language>en</dc:language>")
    # Include citation references as dc:relation entries
    from articles import extract_bibtex, parse_bibtex_entries
    bibtex = extract_bibtex(article.get("source_markdown", ""))
    if bibtex:
        for entry in parse_bibtex_entries(bibtex):
            ref_parts = []
            if entry.get("author"):
                ref_parts.append(entry["author"])
            if entry.get("title"):
                ref_parts.append(entry["title"])
            if entry.get("year"):
                ref_parts.append(entry["year"])
            if entry.get("doi"):
                ref_parts.append(f"doi:{entry['doi']}")
            ref = ", ".join(ref_parts) if ref_parts else entry.get("key", "")
            if ref:
                lines.append(f"  <dc:relation>Cites: {escape(ref)}</dc:relation>")
    lines.append("</oai_dc:dc>")
    return "\n".join(lines)


def _datacite_record(article: dict, authors: list[dict]) -> str:
    """Build oai_datacite metadata (simplified)."""
    lines = ['<resource xmlns="http://datacite.org/schema/kernel-4"']
    lines.append('  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"')
    lines.append(f'  xsi:schemaLocation="http://datacite.org/schema/kernel-4 {METADATA_FORMATS["oai_datacite"]["schema"]}">')
    lines.append(f'  <identifier identifierType="ARK">{escape(article["ark"])}</identifier>')
    lines.append('  <creators>')
    for a in authors:
        lines.append('    <creator>')
        lines.append(f'      <creatorName>{escape(a["name"])}</creatorName>')
        if a.get("orcid"):
            lines.append(f'      <nameIdentifier schemeURI="https://orcid.org/" nameIdentifierScheme="ORCID">{escape(a["orcid"])}</nameIdentifier>')
        if a.get("affiliation"):
            lines.append(f'      <affiliation>{escape(a["affiliation"])}</affiliation>')
        lines.append('    </creator>')
    lines.append('  </creators>')
    lines.append(f'  <titles><title>{escape(article["title"])}</title></titles>')
    if article.get("published_at"):
        lines.append(f'  <publicationYear>{article["published_at"].year}</publicationYear>')
    lines.append(f'  <rightsList><rights rightsURI="{escape(article.get("license_url", ""))}">{escape(article.get("license", ""))}</rights></rightsList>')
    lines.append('  <resourceType resourceTypeGeneral="Preprint">Preprint</resourceType>')
    if article.get("abstract"):
        lines.append(f'  <descriptions><description descriptionType="Abstract">{escape(article["abstract"])}</description></descriptions>')
    lines.append('</resource>')
    return "\n".join(lines)


def _build_record(article: dict, metadata_prefix: str) -> str:
    authors = get_article_authors(article["id"])
    oai_id = _oai_identifier(article["ark"])
    datestamp = _format_date(article["published_at"]) if article["published_at"] else _format_date(article["submitted_at"])

    if metadata_prefix == "oai_dc":
        metadata = _dc_record(article, authors)
    elif metadata_prefix == "oai_datacite":
        metadata = _datacite_record(article, authors)
    else:
        metadata = ""

    return f"""  <record>
    <header>
      <identifier>{escape(oai_id)}</identifier>
      <datestamp>{datestamp}</datestamp>
    </header>
    <metadata>
{metadata}
    </metadata>
  </record>"""


def _build_header(article: dict) -> str:
    oai_id = _oai_identifier(article["ark"])
    datestamp = _format_date(article["published_at"]) if article["published_at"] else _format_date(article["submitted_at"])
    return f"""  <header>
    <identifier>{escape(oai_id)}</identifier>
    <datestamp>{datestamp}</datestamp>
  </header>"""


def _fetch_records(from_date=None, until_date=None, offset=0, limit=PAGE_SIZE):
    """Fetch published articles from DB."""
    query = "SELECT * FROM articles WHERE status = 'published'"
    params = []
    if from_date:
        query += " AND published_at >= %s"
        params.append(from_date)
    if until_date:
        query += " AND published_at <= %s"
        params.append(until_date)
    query += " ORDER BY published_at ASC LIMIT %s OFFSET %s"
    params.extend([limit + 1, offset])  # fetch one extra to check for resumption
    with get_conn().connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return rows


@router.get("/oai")
@router.post("/oai")
def oai_pmh(
    request: Request,
    verb: str = Query(""),
    identifier: str = Query(None),
    metadataPrefix: str = Query(None),
    from_: str = Query(None, alias="from"),
    until: str = Query(None, alias="until"),
    set: str = Query(None, alias="set"),
    resumptionToken: str = Query(None, alias="resumptionToken"),
):
    """OAI-PMH 2.0 endpoint."""
    response_date = _format_date(datetime.now(timezone.utc))
    base_url = f"{config.base_url}/oai"

    # Parse resumption token if present
    if resumptionToken:
        # Format: prefix:offset
        parts = resumptionToken.split(":")
        if len(parts) != 2:
            return Response(_oai_error("badResumptionToken", "Invalid resumption token"), media_type="text/xml")
        metadataPrefix = parts[0]
        try:
            offset = int(parts[1])
        except ValueError:
            return Response(_oai_error("badResumptionToken", "Invalid resumption token"), media_type="text/xml")
    else:
        offset = 0

    # ─── Identify ──────────────────────────────────────────────────────────
    if verb == "Identify":
        body = f"""  <Identify>
    <repositoryName>{escape(REPOSITORY_NAME)}</repositoryName>
    <baseURL>{escape(base_url)}</baseURL>
    <protocolVersion>{PROTOCOL_VERSION}</protocolVersion>
    <adminEmail>{escape(ADMIN_EMAIL)}</adminEmail>
    <earliestDatestamp>{_format_date(datetime(2026, 1, 1, tzinfo=timezone.utc))}</earliestDatestamp>
    <deletedRecord>{DELETED_RECORD}</deletedRecord>
    <granularity>{GRANULARITY}</granularity>
  </Identify>"""

    # ─── ListMetadataFormats ───────────────────────────────────────────────
    elif verb == "ListMetadataFormats":
        formats = []
        for prefix, info in METADATA_FORMATS.items():
            formats.append(f"""    <metadataFormat>
      <metadataPrefix>{prefix}</metadataPrefix>
      <schema>{info['schema']}</schema>
      <metadataNamespace>{info['namespace']}</metadataNamespace>
    </metadataFormat>""")
        body = f"  <ListMetadataFormats>\n" + "\n".join(formats) + "\n  </ListMetadataFormats>"

    # ─── ListSets ──────────────────────────────────────────────────────────
    elif verb == "ListSets":
        return Response(_oai_error("noSetHierarchy", "This repository does not support sets"), media_type="text/xml")

    # ─── GetRecord ─────────────────────────────────────────────────────────
    elif verb == "GetRecord":
        if not identifier or not metadataPrefix:
            return Response(_oai_error("badArgument", "identifier and metadataPrefix are required"), media_type="text/xml")
        if metadataPrefix not in METADATA_FORMATS:
            return Response(_oai_error("cannotDisseminateFormat", f"Unknown metadata prefix: {metadataPrefix}"), media_type="text/xml")
        ark = _parse_ark_from_oai_id(identifier)
        if not ark:
            return Response(_oai_error("idDoesNotExist", "Unknown identifier"), media_type="text/xml")
        with get_conn().connection() as conn:
            row = conn.execute(
                "SELECT * FROM articles WHERE ark = %s AND status = 'published'", (ark,)
            ).fetchone()
        if not row:
            return Response(_oai_error("idDoesNotExist", "Unknown identifier"), media_type="text/xml")
        body = f"  <GetRecord>\n{_build_record(row, metadataPrefix)}\n  </GetRecord>"

    # ─── ListIdentifiers / ListRecords ─────────────────────────────────────
    elif verb in ("ListIdentifiers", "ListRecords"):
        if not resumptionToken and not metadataPrefix:
            return Response(_oai_error("badArgument", "metadataPrefix is required"), media_type="text/xml")
        if metadataPrefix not in METADATA_FORMATS:
            return Response(_oai_error("cannotDisseminateFormat", f"Unknown metadata prefix: {metadataPrefix}"), media_type="text/xml")

        from_dt = None
        until_dt = None
        if from_:
            try:
                from_dt = datetime.strptime(from_, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                return Response(_oai_error("badArgument", "Invalid from date"), media_type="text/xml")
        if until:
            try:
                until_dt = datetime.strptime(until, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                return Response(_oai_error("badArgument", "Invalid until date"), media_type="text/xml")

        rows = _fetch_records(from_date=from_dt, until_date=until_dt, offset=offset)
        if not rows:
            return Response(_oai_error("noRecordsMatch", "No records match the criteria"), media_type="text/xml")

        has_more = len(rows) > PAGE_SIZE
        rows = rows[:PAGE_SIZE]

        if verb == "ListIdentifiers":
            headers = "\n".join(_build_header(r) for r in rows)
            body = f"  <ListIdentifiers>\n{headers}\n  </ListIdentifiers>"
        else:
            records = "\n".join(_build_record(r, metadataPrefix) for r in rows)
            body = f"  <ListRecords>\n{records}\n  </ListRecords>"

        if has_more:
            next_offset = offset + PAGE_SIZE
            token = f"{metadataPrefix}:{next_offset}"
            body += f"""
  <resumptionToken>{token}</resumptionToken>"""

    else:
        return Response(_oai_error("badVerb", f"Unknown verb: {verb}"), media_type="text/xml")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://www.openarchives.org/OAI/2.0/ http://www.openarchives.org/OAI/2.0/OAI-PMH.xsd">
  <responseDate>{response_date}</responseDate>
  <request verb="{verb}">{escape(base_url)}</request>
{body}
</OAI-PMH>"""

    return Response(xml, media_type="text/xml")
