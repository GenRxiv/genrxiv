# Contributing to GenRxiv

GenRxiv is pre-launch and small. That means there's real room to shape it, and
that most of what's needed isn't code.

## What would help most right now

**Policy.** The hardest open questions aren't technical. What counts as
"AI-generated"? What must an author disclose, and in how much detail? What
happens when someone submits a hundred papers in a week? These need people who
have thought about scholarly publishing, not just people who can write Python.
Open an issue tagged `policy`.

**Moderation.** An archive that accepts AI-generated work will attract volume.
We need moderators before we need scale, not after.

**Early authors.** If you have work that fits — research you generated or
co-generated with AI and want in the open — being an early submitter is one of
the most useful things you can do. It tells us where the submission process
breaks.

**Code.** The FastAPI application, the conversion service, the web UI, the
nginx config, the splash page. See the issues list.

## Reporting a security issue

Don't open a public issue. The conversion service runs untrusted
author-submitted LaTeX, so sandbox escapes are the sharpest class of bug here
and we'd rather hear about them privately first. Email the address on the
organisation profile.

## Working on code

1. Fork and branch from `main`.
2. Keep pull requests focused — one concern per PR.
3. If you're changing the conversion service, say in the PR what you did to
   check the sandboxing still holds. Malformed and hostile `.tex` inputs are
   part of the test surface, not an edge case.
4. Describe what you changed and why. Screenshots help for anything visual.

### Secret scanning

A pre-commit hook blocks credentials from entering git history. To set it
up after cloning:

```bash
# Option A: lightweight (no dependencies)
cp scripts/pre-commit.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit

# Option B: thorough (installs gitleaks + checks)
pip install pre-commit
pre-commit install
```

Option B gives you [gitleaks](https://github.com/gitleaks/gitleaks) for
proper entropy-based secret detection, plus YAML validation, large-file
checks, and whitespace trimming. Option A is a grep-based check with zero
dependencies — better than nothing, but not as thorough.

Never commit `.env`, private keys, tokens, or passwords. The `.gitignore`
excludes these, but the hook is a second line of defense.

## Disclosing AI assistance in contributions

If you used AI to write a contribution, say so in the pull request. Not because
it's discouraged — this project would be a strange place to discourage it — but
because a project premised on disclosure should practise it.

## Code of conduct

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
