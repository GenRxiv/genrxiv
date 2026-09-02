#!/bin/sh
# Patch OrcidManager.php to use a fixed redirect URI
# The redirect URI registered at ORCID is:
#   https://genrxiv.org/genrxiv/orcidVerify
# But OJS generates:
#   https://genrxiv.org/app/genrxiv/orcid/authorizeOrcid
# This patch makes OJS use the registered URI.

ORCID=/var/www/html/lib/pkp/classes/orcid/OrcidManager.php

# Check if already patched
if grep -q 'GenRxiv ORCID redirect patch' "$ORCID" 2>/dev/null; then
    echo "[OJS Patch] OrcidManager already patched"
    exit 0
fi

# Replace the redirect URL construction with a fixed URL
# The original code builds the URL from the dispatcher; we override it
# to use the registered ORCID redirect URI.
sed -i '/We need to construct a page url/i\        // GenRxiv ORCID redirect patch: use the URI registered at ORCID\n        $redirectUrl = "https://genrxiv.org/genrxiv/orcidVerify";' "$ORCID"

# Also comment out the original dispatcher URL construction
# by wrapping it in a false condition
sed -i 's|\$redirectUrl = \$request->getDispatcher()->url(|if (false) \$redirectUrl = \$request->getDispatcher()->url(|' "$ORCID"

echo "[OJS Patch] Fixed ORCID redirect URI to https://genrxiv.org/genrxiv/orcidVerify"
