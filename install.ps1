#Requires -Version 5.1
<#
.SYNOPSIS
Johnny AI Skill bundle bootstrap: verify, present the exact dependency plan,
and require explicit user confirmation before any install effect.

.DESCRIPTION
This entry performs read-only verification and explicit user confirmation,
then hands the confirmed bundle to the stdlib-only bootstrap, which builds
the hash-locked control venv and runs the typed, journaled install
transaction owned by library/local_orchestration/johnny_live_install.py.
Running this script never modifies a company repository, PATH, global Python
or Git.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BundleZip
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Every refusal below carries the way out of it. A code alone is exact and
# useless to the person who ran this: the rules it names are rules they had no
# way to know. The real reader is usually an agent standing between them and
# this window, so each entry also declares whether the refusal is the kind an
# agent may settle by itself.
#
# This table is a copy of the one in
# library/local_orchestration/refusal_guidance.py, because PowerShell cannot
# reach into a Python module. It is not kept in step by hand:
# tests/test_refusal_guidance.py parses this block and compares every category
# and every line against that module.
#
# Categories: AGENT_MAY_RESOLVE, OWNER_MUST_DECIDE, NEVER_AUTO_RESOLVE.
$script:RefusalGuidance = @{
    'INSTALL_BLOCKED_INSIDE_REPOSITORY' = @{
        Category = 'AGENT_MAY_RESOLVE'
        NextSteps = @(
            'The installer refuses to bootstrap from inside a Git checkout, and the folder it was started in is one.',
            'Move the release zip and the installer into a folder that is not inside any Git checkout, such as a new folder on the Desktop, and start it again from there.',
            'Nothing is written into the folder it is launched from either way; the install goes to the per-user root under LOCALAPPDATA.'
        )
    }
    'GIT_UNAVAILABLE' = @{
        Category = 'OWNER_MUST_DECIDE'
        NextSteps = @(
            'Stop: the installer needs the git command and this machine has none on PATH.',
            'Ask the person running this whether to install Git for Windows. Installing software on their machine is theirs to decide.',
            'After they install it, open a new terminal so PATH is picked up, then start the installer again.'
        )
    }
    'BUNDLE_NOT_FOUND' = @{
        Category = 'AGENT_MAY_RESOLVE'
        NextSteps = @(
            'The release zip named on the command line is not there.',
            'Put the published zip beside the installer under exactly the name it was published with, and start the installer again from that folder.',
            'Do not reach for a different archive: the digest check refuses one, and that refusal is not yours to settle.'
        )
    }
    'PYTHON_311_UNAVAILABLE' = @{
        Category = 'OWNER_MUST_DECIDE'
        NextSteps = @(
            'Stop: the control runtime needs Python 3.11 reachable as py -3.11, and this machine has no such interpreter.',
            'Ask the person running this whether to install Python 3.11 from python.org with the py launcher enabled. That is a change to their machine and theirs to decide.',
            'After they install it, start the installer again.'
        )
    }
    'RUNTIME_LOCK_MISSING' = @{
        Category = 'NEVER_AUTO_RESOLVE'
        NextSteps = @(
            'Stop. The archive holds no dependency lock, and the published release holds one, so this archive is not the published release.',
            'What is missing is the list of exact versions and artifact hashes the install was going to be held to. Supplying that list locally would produce an install held to whatever was supplied.',
            'Tell the person running this that the archive they have is not the approved release, show them this code, and let them fetch the release again from where the owner published it.'
        )
    }
    'USER_DECLINED' = @{
        Category = 'NEVER_AUTO_RESOLVE'
        NextSteps = @(
            'Stop. A person read the exact dependency plan and did not type the confirmation word, so consent for this install does not exist.',
            'That prompt is there to reach a human at the keyboard. Whatever an agent puts into it is not consent carried, it is consent manufactured, and afterwards nothing tells an unconsented install apart from a consented one.',
            'Tell the person what the plan contained and let them decide. If they want it, they start the installer themselves.'
        )
    }
    'BOOTSTRAP_MISSING' = @{
        Category = 'NEVER_AUTO_RESOLVE'
        NextSteps = @(
            'Stop. The archive holds no bootstrap module, and the published release holds one, so this archive is not the published release.',
            'The bootstrap is the code that builds the hash-locked control venv. An archive missing it and an archive carrying a different one look the same from here.',
            'Tell the person running this that the archive they have is not the approved release, show them this code, and let them fetch the release again from where the owner published it.'
        )
    }
}

function Write-TypedResult {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [Parameter(Mandatory = $true)][string]$Code
    )
    # No default category. A code with no entry is reported as exactly that and
    # exits on its own number, rather than being handed the mildest category
    # available -- because if forgetting were quiet, and the quiet answer were
    # the permissive one, forgetting would mean admitting.
    if (-not $script:RefusalGuidance.ContainsKey($Code)) {
        Write-Output ('{{"status":"{0}","code":"{1}","category":"UNCLASSIFIED","next_steps":["This refusal code carries no guidance entry. Report the code as it stands and do not treat the refusal as settled."]}}' -f $Status, $Code)
        exit 3
    }
    $entry = $script:RefusalGuidance[$Code]
    $steps = ($entry.NextSteps | ForEach-Object { '"' + $_ + '"' }) -join ','
    # status and code keep their exact leading position: the released wrapper
    # and the acceptance suite already read this line, and this ticket adds
    # fields rather than moving them.
    Write-Output ('{{"status":"{0}","code":"{1}","category":"{2}","next_steps":[{3}]}}' -f $Status, $Code, $entry.Category, $steps)
    foreach ($step in $entry.NextSteps) {
        Write-Output ("  - {0}" -f $step)
    }
}

# P0 boundary: never bootstrap from inside any Git repository checkout.
$gitCommand = Get-Command git -ErrorAction SilentlyContinue
if ($null -ne $gitCommand) {
    $insideRepository = ''
    try {
        $insideRepository = (& git rev-parse --is-inside-work-tree 2>$null)
    } catch {
        $insideRepository = ''
    }
    if ("$insideRepository".Trim() -eq 'true') {
        Write-TypedResult -Status 'BLOCKED' -Code 'INSTALL_BLOCKED_INSIDE_REPOSITORY'
        exit 2
    }
} else {
    Write-TypedResult -Status 'BLOCKED' -Code 'GIT_UNAVAILABLE'
    exit 2
}

if (-not (Test-Path -LiteralPath $BundleZip -PathType Leaf)) {
    Write-TypedResult -Status 'BLOCKED' -Code 'BUNDLE_NOT_FOUND'
    exit 2
}

$archiveHash = (Get-FileHash -LiteralPath $BundleZip -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Output ("Bundle archive SHA-256: {0}" -f $archiveHash)
Write-Output 'Compare this digest with the approved release digest before continuing.'

$pythonProbe = $null
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($null -ne $pyLauncher) {
    try {
        $pythonProbe = (& py -3.11 --version 2>$null)
    } catch {
        $pythonProbe = $null
    }
}
if ([string]::IsNullOrWhiteSpace("$pythonProbe")) {
    Write-TypedResult -Status 'BLOCKED' -Code 'PYTHON_311_UNAVAILABLE'
    exit 2
}
Write-Output ("Control Python probe: {0}" -f "$pythonProbe".Trim())

# Present the exact dependency plan from the bundled runtime lock (read-only).
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $BundleZip).Path)
try {
    $lockEntry = $archive.Entries | Where-Object { $_.FullName -eq 'requirements-runtime.lock' }
    if ($null -eq $lockEntry) {
        Write-TypedResult -Status 'BLOCKED' -Code 'RUNTIME_LOCK_MISSING'
        exit 2
    }
    $reader = New-Object System.IO.StreamReader($lockEntry.Open())
    try {
        $lockJson = $reader.ReadToEnd() | ConvertFrom-Json
    } finally {
        $reader.Dispose()
    }
    Write-Output ("Python constraint: {0}" -f $lockJson.python_constraint)
    Write-Output 'Exact dependency plan (name / version / artifact SHA-256):'
    foreach ($dependency in $lockJson.dependencies) {
        foreach ($artifact in $dependency.artifacts) {
            Write-Output ("  {0} {1} {2}" -f $dependency.normalized_name, $dependency.exact_version, $artifact.sha256)
        }
    }
} finally {
    $archive.Dispose()
}

$confirmation = Read-Host 'Type INSTALL to confirm this exact plan'
if ($confirmation -cne 'INSTALL') {
    Write-TypedResult -Status 'BLOCKED' -Code 'USER_DECLINED'
    exit 2
}

# Live install: extract the stdlib-only bootstrap from the confirmed bundle
# and hand it the bundle plus the per-user root. The bootstrap creates the
# hash-locked control venv, then the typed transaction running inside that
# venv verifies and installs everything else, journaled and compensable.
$johnnyRoot = $env:JOHNNY_ROOT
if ([string]::IsNullOrWhiteSpace($johnnyRoot)) {
    $johnnyRoot = Join-Path $env:LOCALAPPDATA 'JohnnyRouter'
}
$resolvedBundle = (Resolve-Path -LiteralPath $BundleZip).Path
$bootstrapStage = Join-Path ([System.IO.Path]::GetTempPath()) ('johnny-bootstrap-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $bootstrapStage | Out-Null
try {
    $bootstrapArchive = [System.IO.Compression.ZipFile]::OpenRead($resolvedBundle)
    try {
        $bootstrapEntry = $bootstrapArchive.Entries | Where-Object {
            $_.FullName -eq 'library/local_orchestration/bootstrap_install.py'
        }
        if ($null -eq $bootstrapEntry) {
            Write-TypedResult -Status 'BLOCKED' -Code 'BOOTSTRAP_MISSING'
            exit 2
        }
        $bootstrapPath = Join-Path $bootstrapStage 'bootstrap_install.py'
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile($bootstrapEntry, $bootstrapPath, $true)
    } finally {
        $bootstrapArchive.Dispose()
    }
    & py -3.11 -X utf8 $bootstrapPath --bundle $resolvedBundle --root $johnnyRoot
    exit $LASTEXITCODE
} finally {
    Remove-Item -Recurse -Force $bootstrapStage -ErrorAction SilentlyContinue
}
