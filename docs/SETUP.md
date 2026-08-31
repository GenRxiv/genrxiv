# GenRxiv — Server Setup Guide

## 0. Before you start
Check the Mac's chip: `uname -m`
- `x86_64` → use `pkpofficial/ojs:latest` (already set in docker-compose.yml)
- `arm64` → swap the `ojs` image to `teic/docker-pkp-ojs:lts` in docker-compose.yml

## 1. Install Ubuntu Server
Use Ubuntu Server 24.04 LTS (not Desktop — no GUI needed, saves RAM on old hardware).
Flash to a USB with `balenaEtcher` or `dd`, boot the Mac from it (hold Option/Alt at boot),
install, enable OpenSSH during setup so you can manage it headless afterward.

## 2. Install Docker
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# log out/in for the group change to take effect
sudo apt install docker-compose-plugin -y
```

## 3. Set up Cloudflare Tunnel (free, no port forwarding)
1. Add genrxiv.org to Cloudflare (free plan) and point its nameservers there.
2. In the Cloudflare dashboard: **Zero Trust → Networks → Tunnels → Create a tunnel**.
3. Name it (e.g. `genrxiv-prod`), copy the tunnel token.
4. Add a public hostname: `genrxiv.org` → `http://ojs:80` (the docker service name, not localhost).
5. Paste the token into `.env` as `CF_TUNNEL_TOKEN`.

This means your home network never has an open inbound port — Cloudflare terminates
TLS and proxies to the tunnel daemon running in your compose stack.

## 4. Launch the stack
```bash
cp .env.example .env
nano .env   # fill in real passwords + the tunnel token
docker compose up -d
```
`OJS_CLI_INSTALL: 1` runs the installer automatically on first boot. Give it a minute,
then check `docker compose logs -f ojs` for the admin credentials confirmation.

## 5. ORCID author validation
1. Register a free client at https://orcid.org/developer-tools (Public API).
2. Set the redirect URI to `https://genrxiv.org/index/orcidVerify`.
3. In OJS: **Website Settings → Plugins → ORCID Profile plugin** → enable it, paste your
   Client ID/Secret. Set it to *required* for submitting authors if you want hard enforcement.
   This gets you real author disambiguation without building your own identity system.

## 6. Turn on machine-readable access for AI agents / harvesters
1. **OAI-PMH**: enabled by default in OJS at `/genrxiv/oai` — this is the same protocol
   arXiv, bioRxiv, and every other Rxiv site exposes for automated metadata harvesting.
   Point any indexer or agent at that endpoint rather than having them scrape HTML.
2. **robots.txt**: make sure it's permissive for content — you *want* to be crawled.
3. Add a `sitemap.xml` (OJS has a sitemap plugin) and schema.org `ScholarlyArticle`
   JSON-LD on article pages — this is what lets agents parse title/authors/abstract/PDF
   link reliably instead of guessing from page layout.
4. Consider adding a root-level `/llms.txt` pointing at the OAI-PMH endpoint and API docs,
   since that's becoming the informal convention for "here's how an agent should read this site."

## 7. LaTeX / Markdown submission pipeline (phase 2)
OJS doesn't compile TeX out of the box. Plan: a small sidecar service that
- accepts a `.tex` or `.md` submission + assets on upload
- runs **Tectonic** (self-contained LaTeX engine — much lighter than full TeXLive,
  good fit for old hardware) or **Pandoc** (for Markdown) to produce PDF + clean HTML
- stores source, PDF, and HTML as versioned files attached to the OJS submission

This is its own build — happy to spec and write it next once the base server is live.

## 8. Cost-effective path forward
- **Now**: $0/mo — old Mac + Cloudflare Tunnel free tier + your existing internet.
- **If it outgrows a home connection**: Hetzner or a similar low-cost VPS (~€4–5/mo)
  is dramatically cheaper than AWS/GCP for this workload and migration is just moving
  the same docker-compose stack.
- **Backups**: sync the `ojs_files` volume to Backblaze B2 or Cloudflare R2 nightly —
  both are cheap-to-free for the volume a preprint archive generates and neither charges
  egress the way S3 does.
- **Long-term sponsorship**: CLOCKSS and LOCKSS both offer preservation partnerships for
  small open-access repositories — worth approaching once you have a track record of
  submissions, since that's usually what sponsors want to see first.
