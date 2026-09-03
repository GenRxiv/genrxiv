#!/bin/sh
# GenRxiv pre-commit hook — blocks secrets before they enter git history.
#
# This is a lightweight grep-based check. For more thorough scanning,
# install gitleaks (see .pre-commit-config.yaml) or the pre-commit framework.
#
# To install manually:
#   cp scripts/pre-commit.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit

RED='\033[0;31m'
NC='\033[0m'

# Get staged files (added/copied/modified), excluding safe file types
SCAN_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -vE '\.env\.example|\.gitignore|\.toml$|\.yaml$|\.yml$|\.md$|\.po$|\.xml$|\.tpl$|\.svg$|\.png$|LICENSE')

if [ -z "$SCAN_FILES" ]; then
    exit 0
fi

BLOCKED=0

# Check each staged file for secret-like patterns
for file in $SCAN_FILES; do
    # Skip .env.example, docs, and this hook script itself
    case "$file" in
        *.env.example|*SETUP.md|*README.md|*CONTRIBUTING.md|*SECURITY.md|*pre-commit.sh|*.gitleaks.toml|*.pre-commit-config.yaml)
            continue
            ;;
    esac

    # Get the staged diff (added lines only)
    STAGED=$(git diff --cached -- "$file" | grep '^+' | grep -v '^+++')

    # Check for .env file being committed
    case "$file" in
        *.env)
            echo "${RED}BLOCKED: .env file detected in commit${NC}"
            echo "The .env file contains secrets and must not be committed."
            echo "It is in .gitignore — if git is tracking it, run: git rm --cached .env"
            BLOCKED=1
            ;;
    esac

    # Check for private keys
    if echo "$STAGED" | grep -q 'BEGIN.*PRIVATE KEY'; then
        echo "${RED}BLOCKED: Private key detected in $file${NC}"
        BLOCKED=1
    fi

    # Check for secret-like assignment patterns (12+ chars, not placeholders)
    if echo "$STAGED" | grep -qiE '(password|secret|token|api_key|apikey|private_key)[[:space:]]*[=:][[:space:]]*["'"'"']?[A-Za-z0-9+/=_-]{12,}'; then
        # Exclude known placeholders
        MATCHES=$(echo "$STAGED" | grep -iE '(password|secret|token|api_key|apikey|private_key)[[:space:]]*[=:][[:space:]]*["'"'"']?[A-Za-z0-9+/=_-]{12,}')
        REAL_SECRETS=$(echo "$MATCHES" | grep -viE 'changeme|paste_token|your-orcid|your-|placeholder|example|getenv|env\(|\$|random_bytes|base64:.*random|session_token|access_token|_create_session|_token')
        if [ -n "$REAL_SECRETS" ]; then
            echo "${RED}BLOCKED: Potential secret in $file${NC}"
            echo "$REAL_SECRETS" | head -5
            echo ""
            echo "If this is a false positive, add the pattern to .gitleaks.toml"
            echo "and the allowlist in scripts/pre-commit.sh."
            BLOCKED=1
        fi
    fi
done

if [ "$BLOCKED" -ne 0 ]; then
    echo ""
    echo "${RED}Commit rejected: potential secrets detected.${NC}"
    echo "Remove the secrets and try again."
    exit 1
fi

exit 0
