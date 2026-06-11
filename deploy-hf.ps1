$ErrorActionPreference = "Stop"

function Invoke-Git {
    git @args
    if ($LASTEXITCODE -ne 0) { throw "git $args failed (exit $LASTEXITCODE)" }
}

Write-Host "Deploying backend to HF Space..."

Invoke-Git checkout --orphan hf-deploy
Invoke-Git rm -rf --cached .
Invoke-Git checkout HEAD -- Dockerfile requirements.txt .gitattributes README.md backend/
Invoke-Git add .
Invoke-Git commit -m "HF Space: backend-only deploy"
Invoke-Git push space hf-deploy:main --force

Invoke-Git checkout main
Invoke-Git branch -D hf-deploy

Write-Host "Done. Check build progress at https://huggingface.co/spaces/Scooooooootttt/FindArt"
