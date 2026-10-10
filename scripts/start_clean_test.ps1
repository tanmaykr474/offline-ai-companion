# Run Nova with a fresh SQLite database while preserving normal configuration.
param([switch]$ShowTranscript)

$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskProjectRoot '.venv\Scripts\python.exe'
$taskAssistant = Join-Path $PSScriptRoot 'always_on_assistant.py'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'The project virtual environment is missing. Set up .venv before running this script.'
}
$taskSessionId = [Guid]::NewGuid().ToString('N')
$taskDatabase = Join-Path $taskProjectRoot "sample-data\memory\clean-tests\$taskSessionId\companion.db"
$taskPreviousDatabase = [Environment]::GetEnvironmentVariable('DATABASE_PATH', 'Process')
$taskPreviousTranscriptDebug = [Environment]::GetEnvironmentVariable('NOVA_TRANSCRIPT_DEBUG', 'Process')
$taskPreviousDirectory = Get-Location
try {
    $env:DATABASE_PATH = $taskDatabase
    if ($ShowTranscript) {
        $env:NOVA_TRANSCRIPT_DEBUG = 'true'
        Write-Host 'Transcript display enabled. Personal speech is visible in this console; recognized credentials are omitted.'
    }
    Set-Location -LiteralPath $taskProjectRoot
    Write-Host 'Nova clean test session. Existing saved data is preserved.'
    Write-Host "Test database: $taskDatabase"
    Write-Host 'This launch starts empty. Restart with the same database path to test persistence.'
    & $taskPython $taskAssistant
} finally {
    [Environment]::SetEnvironmentVariable('DATABASE_PATH', $taskPreviousDatabase, 'Process')
    [Environment]::SetEnvironmentVariable('NOVA_TRANSCRIPT_DEBUG', $taskPreviousTranscriptDebug, 'Process')
    Set-Location -LiteralPath $taskPreviousDirectory.Path
}
