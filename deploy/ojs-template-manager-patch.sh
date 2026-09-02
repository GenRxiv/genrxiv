#!/bin/sh
# Patch PKPTemplateManager.php to fix undefined $site variable
# Bug in OJS 3.5.0.5: $site is only defined when !$currentContext,
# but used on line 293 regardless of context.

TMPL=/var/www/html/lib/pkp/classes/template/PKPTemplateManager.php

# Check if already patched
if grep -q 'Patch.*undefined.*site' "$TMPL" 2>/dev/null; then
    echo "[OJS Patch] Template manager already patched"
    exit 0
fi

# Add $site assignment before the supportedLocales check (line ~293)
# The pattern: if (count($supportedLocales = $currentContext?->getSupportedLocales() ?? $site->getSupportedLocales())
# We need to add: $site = $request->getSite(); before it
sed -i 's|if (count(\$supportedLocales = \$currentContext?->getSupportedLocales() ?? \$site->getSupportedLocales())|// Patch: ensure $site is defined\n                $site = $request->getSite();\n                if (count($supportedLocales = $currentContext?->getSupportedLocales() ?? $site->getSupportedLocales())|' "$TMPL"

echo "[OJS Patch] Fixed undefined \$site variable in PKPTemplateManager.php"
