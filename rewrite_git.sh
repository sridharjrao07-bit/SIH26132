#!/bin/bash

export FILTER_BRANCH_SQUELCH_WARNING=1

git filter-branch -f --env-filter '
    if [ "$GIT_AUTHOR_EMAIL" != "49699333+dependabot[bot]@users.noreply.github.com" ]; then
        export GIT_AUTHOR_NAME="sridharjrao07-bit"
        export GIT_AUTHOR_EMAIL="sridharjrao07@gmail.com"
        export GIT_COMMITTER_NAME="sridharjrao07-bit"
        export GIT_COMMITTER_EMAIL="sridharjrao07@gmail.com"
    fi
' --msg-filter '
    python -c "import sys; text=sys.stdin.read(); text=text.replace('from sridharjrao07-bit/arena/', 'from sridharjrao07-bit/feature/sih26132/'); lines=[l for l in text.splitlines() if not l.startswith('Co-authored-by: arena-agent') and not l.startswith('Co-authored-by: core-agent')]; print('\n'.join(lines))"
' -- --all
