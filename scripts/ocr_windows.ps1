# Read the text on pictures with the OCR engine built into Windows (no install, nothing leaves the PC).
#
#   .\scripts\ocr_windows.ps1 -Files a.jpg,b.png            # prints one JSON line per file
#   .\scripts\ocr_windows.ps1 -List data\media\to_ocr.txt -Out data\media\ocr.jsonl
#
# It reads each picture with the English and the Arabic engines (when installed) and joins the
# two texts, so boxes printed in either language can be checked.
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
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapTransform, Windows.Graphics.Imaging, ContentType = WindowsRuntime]

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

$engines = @()
foreach ($tag in @("en-US", "ar-SA")) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language($tag)))
    if ($null -ne $engine) { $engines += $engine }
}
if ($engines.Count -eq 0) { throw "no OCR language (English or Arabic) is installed" }
$tags = ($engines | ForEach-Object { $_.RecognizerLanguage.LanguageTag }) -join "+"

if ($List) { $Files = @(Get-Content -Path $List -Encoding UTF8 | Where-Object { $_.Trim() }) }
$writer = $null
if ($Out) { $writer = New-Object System.IO.StreamWriter($Out, $true, (New-Object System.Text.UTF8Encoding($false))) }

foreach ($path in $Files) {
    $row = [ordered]@{ file = $path; language = $tags; text = ""; error = $null }
    try {
        $full = (Resolve-Path -LiteralPath $path).Path
        $file = Wait-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($full)) ([Windows.Storage.StorageFile])
        $stream = Wait-Operation ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $decoder = Wait-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        # Small pictures give the engine too few pixels per letter: enlarge them (at most 4 times).
        $smallest = [Math]::Min($decoder.PixelWidth, $decoder.PixelHeight)
        $scale = [Math]::Min(4, [Math]::Max(1, [Math]::Ceiling(900 / [Math]::Max($smallest, 1))))
        if ($scale -gt 1) {
            $transform = New-Object Windows.Graphics.Imaging.BitmapTransform
            $transform.ScaledWidth = [uint32]($decoder.PixelWidth * $scale)
            $transform.ScaledHeight = [uint32]($decoder.PixelHeight * $scale)
            $transform.InterpolationMode = [Windows.Graphics.Imaging.BitmapInterpolationMode]::Fant
            $bitmap = Wait-Operation ($decoder.GetSoftwareBitmapAsync($decoder.BitmapPixelFormat, [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied, $transform, [Windows.Graphics.Imaging.ExifOrientationMode]::IgnoreExifOrientation, [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage)) ([Windows.Graphics.Imaging.SoftwareBitmap])
        }
        else {
            $bitmap = Wait-Operation ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        }
        $texts = foreach ($engine in $engines) {
            (Wait-Operation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])).Text
        }
        $row.text = (($texts -join " ") -replace "\s+", " ").Trim()
    }
    catch { $row.error = $_.Exception.Message }
    $line = $row | ConvertTo-Json -Compress
    if ($writer) { $writer.WriteLine($line); $writer.Flush() } else { $line }
}
if ($writer) { $writer.Dispose() }
