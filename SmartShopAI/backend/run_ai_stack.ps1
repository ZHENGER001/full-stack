param(
    [ValidateSet("start", "infra", "index", "backend", "stop", "status")]
    [string]$Action = "start",
    [string]$MilvusVersion = "v2.5.27",
    [string]$MilvusCompose = "docker-compose.milvus.yml",
    [string]$EmbeddingCompose = "docker-compose.embedding.yml",
    [string]$DockerBin = "docker",
    [string]$PythonBin = "python",
    [string]$AppHost = "0.0.0.0",
    [int]$AppPort = 8000,
    [int]$EmbeddingWaitSeconds = 600
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RootDir

$MilvusUrl = "https://github.com/milvus-io/milvus/releases/download/$MilvusVersion/milvus-standalone-docker-compose.yml"

function Require-Command {
    param([string]$Name)
    if (-not (Test-Path $Name) -and -not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name"
    }
}

function Invoke-Native {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

function Ensure-Env {
    if (-not (Test-Path ".env")) {
        Copy-Item ".env.example" ".env"
        Write-Host "Created .env from .env.example. Edit .env if you need different ports, keys, or model endpoints."
    }
}

function Ensure-Docker {
    Require-Command $DockerBin
    Invoke-Native -FilePath $DockerBin -Arguments @("ps")
}

function Download-MilvusCompose {
    if (Test-Path $MilvusCompose) {
        return
    }
    Write-Host "Downloading Milvus compose: $MilvusUrl"
    Invoke-WebRequest -Uri $MilvusUrl -OutFile $MilvusCompose
}

function Check-Gpu {
    Write-Host "Checking NVIDIA GPU access from Docker..."
    Invoke-Native -FilePath $DockerBin -Arguments @("run", "--rm", "--gpus", "all", "nvidia/cuda:12.4.1-base-ubuntu22.04", "nvidia-smi")
}

function Start-Milvus {
    Download-MilvusCompose
    Write-Host "Starting Milvus..."
    Invoke-Native -FilePath $DockerBin -Arguments @("compose", "-f", $MilvusCompose, "up", "-d")
}

function Start-Embedding {
    Write-Host "Starting Qwen3-Embedding-0.6B GPU service..."
    Invoke-Native -FilePath $DockerBin -Arguments @("compose", "-f", $EmbeddingCompose, "up", "-d")
}

function Wait-Embedding {
    $deadline = (Get-Date).AddSeconds($EmbeddingWaitSeconds)
    $body = '{"model":"Qwen/Qwen3-Embedding-0.6B","input":["health check"]}'

    Write-Host "Waiting for embedding service at http://127.0.0.1:8080/v1/embeddings ..."
    while ((Get-Date) -lt $deadline) {
        curl.exe --noproxy "*" -s -f `
            -X POST "http://127.0.0.1:8080/v1/embeddings" `
            -H "Content-Type: application/json" `
            -d $body | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Embedding service is ready."
            return
        }
        Write-Host "Embedding service is not ready yet."
        Start-Sleep -Seconds 10
    }
    throw "Embedding service did not become ready within $EmbeddingWaitSeconds seconds."
}

function Build-Index {
    Write-Host "Building Milvus product embedding index..."
    Invoke-Native -FilePath $PythonBin -Arguments @("scripts\build_milvus_index.py", "--recreate")
}

function Assert-Port-Free {
    param([int]$Port)
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listeners) {
        $owners = ($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
        throw "Port $Port is already in use by PID(s): $owners. Stop that process or run with -AppPort another_port."
    }
}

function Start-Backend {
    Assert-Port-Free -Port $AppPort
    Write-Host "Starting SmartShopAI backend on ${AppHost}:${AppPort}..."
    Invoke-Native -FilePath $PythonBin -Arguments @("-m", "uvicorn", "app.main:app", "--host", $AppHost, "--port", "$AppPort")
}

function Stop-Stack {
    Write-Host "Stopping embedding service..."
    & $DockerBin compose -f $EmbeddingCompose down
    if (Test-Path $MilvusCompose) {
        Write-Host "Stopping Milvus..."
        & $DockerBin compose -f $MilvusCompose down
    }
}

function Show-Status {
    & $DockerBin ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
}

switch ($Action) {
    "start" {
        Ensure-Env
        Ensure-Docker
        Check-Gpu
        Start-Milvus
        Start-Embedding
        Wait-Embedding
        Build-Index
        Start-Backend
    }
    "infra" {
        Ensure-Env
        Ensure-Docker
        Check-Gpu
        Start-Milvus
        Start-Embedding
        Wait-Embedding
    }
    "index" {
        Ensure-Env
        Build-Index
    }
    "backend" {
        Ensure-Env
        Start-Backend
    }
    "stop" {
        Ensure-Docker
        Stop-Stack
    }
    "status" {
        Ensure-Docker
        Show-Status
    }
}
