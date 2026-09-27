git merge origin/main --no-commit

$conflicted_files = git diff --name-only --diff-filter=U | ForEach-Object { $_ }

foreach ($file in $conflicted_files) {
    if ($file -match "^web/") {
        Write-Host "Keeping OURS (feat/visual-pass) for web file: $file"
        git checkout --ours "$file"
        git add "$file"
    } else {
        Write-Host "Keeping THEIRS (main) for backend file: $file"
        git checkout --theirs "$file"
        git add "$file"
    }
}
