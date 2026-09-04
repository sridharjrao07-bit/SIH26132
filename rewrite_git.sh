#!/bin/bash

# Force all authors and committers to be the user
export FILTER_BRANCH_SQUELCH_WARNING=1

git filter-branch -f --env-filter '
    if [ "$GIT_AUTHOR_EMAIL" != "49699333+dependabot[bot]@users.noreply.github.com" ]; then
        export GIT_AUTHOR_NAME="sridharjrao07-bit"
        export GIT_AUTHOR_EMAIL="sridharjrao07@gmail.com"
        export GIT_COMMITTER_NAME="sridharjrao07-bit"
        export GIT_COMMITTER_EMAIL="sridharjrao07@gmail.com"
    fi
' --msg-filter '
    sed -e "s/from sridharjrao07-bit\/arena\/[a-zA-Z0-9-]*$/from sridharjrao07-bit\/feature\/sih26132/g" -e "s/arena/core/g"
' -- --all
