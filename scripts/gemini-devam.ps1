<#
.SYNOPSIS
  Claude'un hakkı bittiğinde işi Gemini (Antigravity CLI, agy) ile kaldığı yerden sürdürür (spec 0027).

.DESCRIPTION
  agy'yi önce PATH'te, sonra %USERPROFILE%\.gemini\bin\agy.exe konumunda arar ve depo kökünde
  etkileşimli açar; açılış talimatı Gemini'ye işin durumunu dosyalardan okutur ve onay gelene
  kadar hiçbir şey başlatmamasını söyler. Varsayılan izin modu kullanılır: izinleri otomatik geçen
  hiçbir seçenek (--dangerously-skip-permissions, --mode) verilmez. Sır okumaz, dosya yazmaz.

.PARAMETER Prova
  Gemini'yi açmaz; bulunan agy yolunu, çalışma klasörünü ve argümanları yazar (deneme ve test için).

.EXAMPLE
  scripts\gemini-devam.ps1
#>
[CmdletBinding()]
param([switch]$Prova)

$ErrorActionPreference = 'Stop'
# A redirected console is in the local code page (cp857/cp1254); write UTF-8 there so Turkish text
# survives a pipe. The interactive console is left as it is.
if ([Console]::IsOutputRedirected -or [Console]::IsErrorRedirected) {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
}

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$userHome = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
$fallback = Join-Path (Join-Path (Join-Path $userHome '.gemini') 'bin') 'agy.exe'

$agy = $null
$onPath = Get-Command -Name agy -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if ($onPath) {
    $agy = $onPath.Source
} elseif (Test-Path -LiteralPath $fallback -PathType Leaf) {
    $agy = $fallback
}

if (-not $agy) {
    [Console]::Error.WriteLine('Gemini (Antigravity CLI, agy) bulunamadı; Gemini açılmadı. Aranan konumlar:')
    [Console]::Error.WriteLine('  1. PATH (agy komutu)')
    [Console]::Error.WriteLine("  2. $fallback")
    [Console]::Error.WriteLine('Kurulum ipucu: Antigravity CLI''ı kurun, PATH için bir kez "agy install" çalıştırın ve')
    [Console]::Error.WriteLine('"agy" ile Google hesabınızla giriş yapın; sonra bu komutu yeniden çalıştırın.')
    exit 1
}

# Opening instruction (spec 0027, Req. 6). No double quotes: Windows PowerShell 5.1 breaks a native
# argument that contains them.
$talimat = @(
    'AGENTS.md dosyasını oku ve kurallarına uy. Bu oturum, Claude ile yürüyen işi kaldığı yerden sürdürür.'
    'Önce yalnızca oku ve şunları çıkar: git branch ve HEAD commit; specs/active/ altındaki her spec ve Status satırı'
    '(birden çok spec varsa hepsini Status değerleriyle listele; numarası branch adındaki numarayla eşleşen spec ana iştir);'
    'ana işin planındaki (specs/plans/NNNN-plan.md) Approved by / on satırı ve bitmemiş ilk adım'
    '(dalda [plan NNNN/k] commit''i olmayan ilk k); git status ile commit edilmemiş değişiklikler;'
    've .claude/handoff.local.md devir notu.'
    'Devir notu yoksa ya da notta kayıtlı branch veya HEAD şimdikinden farklıysa notun yok ya da eski olduğunu açıkça söyle'
    've durumu yalnızca dosyalardan ve git''ten çıkar.'
    'Aktif spec yoksa ve çalışma ağacı temizse aktif iş yok de ve yeni iş için /analyze öner; hiçbir şey başlatma.'
    'Sonra kalınan aşamayı ve sıradaki segmenti komutuyla öner: /analyze, /anew-plan, /build, /review ya da /verify'
    '(Antigravity''de PLAN komutu /anew-plan''dır; /plan yerleşik bir komuttur, kullanma).'
    'Onayım gelene kadar hiçbir dosyayı değiştirme, hiçbir segment başlatma ve durumu okumak için gereken salt okunur'
    'git komutları dışında hiçbir komut çalıştırma.'
) -join ' '

$arguments = @('-i', $talimat)

if ($Prova) {
    Write-Output "agy: $agy"
    Write-Output "Çalışma klasörü: $root"
    for ($i = 0; $i -lt $arguments.Count; $i++) {
        Write-Output ("Argüman {0}: {1}" -f ($i + 1), $arguments[$i])
    }
    exit 0
}

Push-Location -LiteralPath $root
try {
    & $agy @arguments
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $code
