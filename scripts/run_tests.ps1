chcp 65001 > $null
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = (Resolve-Path "$PSScriptRoot\..\src").Path

$py = "python"
foreach ($cand in @(
  (Join-Path $env:USERPROFILE "anaconda3\envs\surveillance\python.exe"),
  (Join-Path $env:USERPROFILE "miniconda3\envs\surveillance\python.exe"),
  (Join-Path $env:USERPROFILE "AppData\Local\anaconda3\envs\surveillance\python.exe")
)) {
  if (Test-Path $cand) { $py = $cand; break }
}
& $py -m unittest discover -s (Resolve-Path "$PSScriptRoot\..\tests").Path -t (Resolve-Path "$PSScriptRoot\..").Path -v
