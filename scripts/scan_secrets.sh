#!/bin/bash
# Secret scanning script for qzWhatNext
# This script checks staged files for secrets before committing

set -e

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

FAILED=0

echo "🔍 Scanning for secrets in staged files..."

# Common secret patterns (regex)
SECRET_PATTERNS=(
    "AIza[0-9A-Za-z_-]{35}"  # Google API key
    "AKIA[0-9A-Z]{16}"  # AWS Access Key ID
    "ya29\.[0-9A-Za-z_-]+"  # Google OAuth access token
    "1//[0-9A-Za-z_-]+"  # Google OAuth refresh token
    "sk-[0-9A-Za-z]{32,}"  # OpenAI/Stripe key
    "xox[baprs]-[0-9A-Za-z-]{10,48}"  # Slack token
    "ghp_[0-9A-Za-z]{36}"  # GitHub personal access token
    "gho_[0-9A-Za-z]{36}"  # GitHub OAuth token
    "ghu_[0-9A-Za-z]{36}"  # GitHub user-to-server token
    "ghr_[0-9A-Za-z]{36}"  # GitHub refresh token
    "-----BEGIN.*PRIVATE KEY-----"  # Private keys
)

# Known secret file names (from .gitignore)
SECRET_FILE_PATTERNS=(
    ".env"
    ".env.local"
    "credentials.json"
    "token.json"
    "sheets_token.json"
    "client_secret*.json"
    "*.pem"  # Private key files
    "*.key"  # Key files
)

# Get staged files
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null || echo "")

if [ -z "$STAGED_FILES" ]; then
    echo -e "${YELLOW}⚠ No files staged for commit${NC}"
    exit 0
fi

echo "📋 Staged files:"
echo "$STAGED_FILES" | sed 's/^/  - /'

# Check for known secret files
echo -e "\n🔐 Checking for known secret files..."
for file in $STAGED_FILES; do
    for pattern in "${SECRET_FILE_PATTERNS[@]}"; do
        if [[ "$file" == $pattern ]] || [[ "$file" == *"$pattern"* ]]; then
            echo -e "${RED}✗ SECRET FILE DETECTED: $file${NC}"
            echo -e "${RED}  This file should be in .gitignore!${NC}"
            FAILED=1
        fi
    done
done

# Check file contents for secret patterns
echo -e "\n🔎 Scanning file contents for secret patterns..."
for file in $STAGED_FILES; do
    if [ -f "$file" ] && [ ! -d "$file" ]; then
        # Skip binary files
        if file "$file" | grep -q "text"; then
            for pattern in "${SECRET_PATTERNS[@]}"; do
                if grep -qiE "$pattern" "$file" 2>/dev/null; then
                    matches=$(grep -iE "$pattern" "$file" 2>/dev/null | head -1 | cut -c1-80)
                    echo -e "${RED}✗ POTENTIAL SECRET DETECTED in $file${NC}"
                    echo -e "${RED}  Pattern matched: ${pattern:0:30}...${NC}"
                    if [ ! -z "$matches" ]; then
                        echo -e "${RED}  Sample match: ${matches}...${NC}"
                    fi
                    FAILED=1
                fi
            done
        fi
    fi
done

# Verify .gitignore has common secret patterns
echo -e "\n✅ Verifying .gitignore configuration..."
if [ -f .gitignore ]; then
    REQUIRED_PATTERNS=(".env" "credentials.json" "token.json" "sheets_token.json" "client_secret*.json")
    for pattern in "${REQUIRED_PATTERNS[@]}"; do
        if ! grep -qE "^${pattern}$|^.*${pattern}" .gitignore 2>/dev/null; then
            echo -e "${YELLOW}⚠ Warning: '$pattern' pattern not found in .gitignore${NC}"
        fi
    done
fi

if [ $FAILED -eq 1 ]; then
    echo -e "\n${RED}❌ SECRET SCAN FAILED${NC}"
    echo -e "${RED}Please remove secrets before committing!${NC}"
    echo -e "${YELLOW}Actions to take:${NC}"
    echo -e "  1. Remove secret files from staging: git reset HEAD <file>"
    echo -e "  2. Add secret files to .gitignore if needed"
    echo -e "  3. Use git filter-branch or BFG to remove secrets from history if already committed"
    exit 1
else
    echo -e "\n${GREEN}✓ Secret scan passed - safe to commit${NC}"
    exit 0
fi

