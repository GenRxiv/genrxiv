# Security Policy

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

The GenRxiv conversion service runs untrusted author-submitted LaTeX, so
sandbox escapes and remote code execution are the sharpest class of bug
here. We need to hear about those privately before they're public.

Please report vulnerabilities to **security@genrxiv.org** with:

- A description of the issue and its impact
- Steps to reproduce, including any crafted input
- The version or commit hash you tested against

You should receive a response within 72 hours. If you don't, follow up —
the message may have been filtered.

## Scope

**In scope:**

- The conversion service (`convert-service/`) — sandbox escapes, file
  system access outside the job directory, network access during
  compilation, resource exhaustion attacks
- The OJS deployment (`deploy/`) — authentication bypass, privilege
  escalation, injection through the submission workflow
- The nginx routing layer — request smuggling, path traversal, bypass
  of the `/app/` subpath isolation
- The signup API — injection, data exfiltration, abuse vectors

**Out of scope:**

- Vulnerabilities in OJS core or its bundled plugins — report those to
  [PKP](https://github.com/pkp/pkp-lib/security) directly
- Vulnerabilities in third-party dependencies (Tectonic, Pandoc,
  PostgreSQL, nginx) — report to the upstream project
- Issues that require already having administrative access
- Spam or content abuse on the archive itself — that's moderation, not
  security

## Disclosure

We follow coordinated disclosure:

1. You report the issue privately.
2. We acknowledge and triage within 72 hours.
3. We work on a fix and agree on a disclosure timeline with you.
4. Once a fix is released, we publish a security advisory and credit
   you (unless you prefer to remain anonymous).

## Security Measures in Place

- **Sandboxed LaTeX compilation:** Tectonic is invoked with
  `--untrusted`, which disables shell-escape and restricts file access
  to the job directory. Each job runs in its own temporary directory
  that is deleted after compilation.
- **Hard timeouts:** Compilation is capped at 60 seconds wall-clock
  time. Jobs that exceed the limit are killed.
- **Upload size limits:** 25 MB maximum for source archives.
- **Zip extraction safety:** Archives are checked for path traversal
  before extraction.
- **No published ports on the conversion service:** It is only
  reachable through the nginx reverse proxy, not directly from the
  network.
- **Secrets via environment variables:** No credentials are stored in
  the repository. All secrets flow through `.env` (gitignored) and are
  injected as environment variables at container startup.
