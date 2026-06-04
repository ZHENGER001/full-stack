param(
    [string]$Version = "v2.5.27",
    [string]$ComposeFile = "docker-compose.milvus.yml"
)

$ErrorActionPreference = "Stop"
$backendDir = Split-Path -Parent $PSScriptRoot
$target = Join-Path $backendDir $ComposeFile
$url = "https://github.com/milvus-io/milvus/releases/download/$Version/milvus-standalone-docker-compose.yml"

Write-Host "Downloading Milvus standalone compose: $url"
Invoke-WebRequest -Uri $url -OutFile $target

Write-Host "Starting Milvus with $target"
docker compose -f $target up -d

Write-Host "Milvus should listen on http://localhost:19530 after startup."
