#!/bin/bash
# s67c packet sums: every regular file under tools/s67c except SHA256SUMS itself, sorted, sha256 (shasum -a 256).  = s66dev's make_sums.sh with the folder changed.
cd /Users/jerryyu/Projects/shengji-wt/claude-s67c-screen/tools/s67c || exit 3
find . -type f ! -name SHA256SUMS ! -name '.DS_Store' ! -path '*/__pycache__/*' -print0 | sort -z | xargs -0 shasum -a 256 > SHA256SUMS && shasum -a 256 -c SHA256SUMS > /dev/null && echo "SHA256SUMS $(shasum -a 256 SHA256SUMS | cut -d' ' -f1) ($(wc -l < SHA256SUMS | tr -d ' ') entries, all verify)"
