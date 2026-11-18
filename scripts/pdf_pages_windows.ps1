# Draw the pages of PDFs as PNG pictures with the renderer built into Windows (no install), so the
# Windows OCR (scripts/ocr_windows.ps1) can read scanned PDFs that have no text layer.
#
#   .\scripts\pdf_pages_windows.ps1 -Files a.pdf,b.pdf -OutDir C:\temp\pages
#
# Prints one JSON line per PDF: { "file": ..., "pages": [png paths], "error": null or text }.
# Pages are written as <pdf name>-p001.png and so on, 1700 pixels wide (about 200 dpi on A4).

param(
    [Parameter(Mandatory = $true)][string[]]$Files,
    [Parameter(Mandatory = $true)][string]$OutDir,
    [int]$Width = 1700
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]
$null = [Windows.Data.Pdf.PdfPageRenderOptions, Windows.Data.Pdf, ContentType = WindowsRuntime]

$asTaskOperation = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object {
        $_.Name -eq "AsTask" -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq "IAsyncOperation``1"
    })[0]
$asTaskAction = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object {
        $_.Name -eq "AsTask" -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq "IAsyncAction"
    })[0]

function Wait-Operation($operation, [Type]$resultType) {
    $task = $asTaskOperation.MakeGenericMethod($resultType).Invoke($null, @($operation))
    $null = $task.Wait(-1)
    return $task.Result
}

function Wait-Action($action) {
    $task = $asTaskAction.Invoke($null, @($action))
    $null = $task.Wait(-1)
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

foreach ($path in $Files) {
    $row = [ordered]@{ file = $path; pages = @(); error = $null }
    try {
        $full = (Resolve-Path -LiteralPath $path).Path
        $stem = [System.IO.Path]::GetFileNameWithoutExtension($full)
        $file = Wait-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($full)) ([Windows.Storage.StorageFile])
        $document = Wait-Operation ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
        for ($index = 0; $index -lt $document.PageCount; $index++) {
            $page = $document.GetPage($index)
            $options = New-Object Windows.Data.Pdf.PdfPageRenderOptions
            $options.DestinationWidth = [uint32]$Width
            $stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
            Wait-Action ($page.RenderToStreamAsync($stream, $options))
            $target = Join-Path $OutDir ("{0}-p{1:D3}.png" -f $stem, ($index + 1))
            $input = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream)
            $output = [System.IO.File]::Create($target)
            try { $input.CopyTo($output) } finally { $output.Dispose(); $input.Dispose() }
            $row.pages += $target
            $stream.Dispose()
            $page.Dispose()
        }
    }
    catch { $row.error = $_.Exception.Message }
    $row | ConvertTo-Json -Compress
}
