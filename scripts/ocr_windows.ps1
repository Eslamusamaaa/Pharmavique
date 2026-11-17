# Read the text on pictures with the OCR engine built into Windows (no install, nothing leaves the PC).
#
#   .\scripts\ocr_windows.ps1 -Files a.jpg,b.png            # prints one JSON line per file
#   .\scripts\ocr_windows.ps1 -List data\media\to_ocr.txt -Out data\media\ocr.jsonl
#
# The languages are the ones installed for the Windows user profile (Settings > Language).
# Files Windows cannot decode (for example WebP without its extension) get "error" set.

param(
    [string[]]$Files = @(),
    [string]$List,
    [string]$Out
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime]

$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object {
        $_.Name -eq "AsTask" -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq "IAsyncOperation``1"
    })[0]

function Wait-Operation($operation, [Type]$resultType) {
    $task = $asTask.MakeGenericMethod($resultType).Invoke($null, @($operation))
    $null = $task.Wait(-1)
    return $task.Result
}

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { throw "no OCR language is installed for this Windows profile" }

if ($List) { $Files = @(Get-Content -Path $List -Encoding UTF8 | Where-Object { $_.Trim() }) }
$writer = $null
if ($Out) { $writer = New-Object System.IO.StreamWriter($Out, $true, (New-Object System.Text.UTF8Encoding($false))) }

foreach ($path in $Files) {
    $row = [ordered]@{ file = $path; language = $engine.RecognizerLanguage.LanguageTag; text = ""; error = $null }
    try {
        $full = (Resolve-Path -LiteralPath $path).Path
        $file = Wait-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($full)) ([Windows.Storage.StorageFile])
        $stream = Wait-Operation ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $decoder = Wait-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Wait-Operation ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $result = Wait-Operation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        $row.text = ($result.Text -replace "\s+", " ").Trim()
    }
    catch { $row.error = $_.Exception.Message }
    $line = $row | ConvertTo-Json -Compress
    if ($writer) { $writer.WriteLine($line); $writer.Flush() } else { $line }
}
if ($writer) { $writer.Dispose() }
