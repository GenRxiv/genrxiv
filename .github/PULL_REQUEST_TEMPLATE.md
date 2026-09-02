## What this changes

A clear summary of what this PR does and why.

## Related issue

Fixes #N / Refs #N / No issue (explain why).

## How to test

Steps a reviewer can follow to verify this works:

1. 
2. 
3. 

## AI assistance

If you used AI tools to help write this contribution, say which tools and
how they were used. This project is premised on disclosure — we practise
what we preach.

## Checklist

- [ ] No credentials, tokens, or secrets in the diff
- [ ] `.env` is not tracked
- [ ] If this changes the conversion service, I've considered sandbox
      safety (malformed/hostile `.tex` inputs are part of the test surface)
- [ ] If this changes deployment, I've tested a full `docker compose down`
      and `up` to verify persistence
