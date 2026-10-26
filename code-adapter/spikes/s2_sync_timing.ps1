# S2 follow-up: where does CLI startup go, and what does a small-change sync cost on Django?
$ErrorActionPreference = 'Continue'
$env:CODEGRAPH_TELEMETRY = '0'
$spikes = Split-Path -Parent $MyInvocation.MyCommand.Path
$bundle = Join-Path $spikes 'node_modules\@colbymchenry\codegraph-win32-x64'
$node = Join-Path $bundle 'node.exe'
$cli = Join-Path $bundle 'lib\dist\bin\codegraph.js'
$proj = Join-Path $spikes 'fixtures\django'

function Time-It($label, [scriptblock]$b) {
  $sw = [Diagnostics.Stopwatch]::StartNew(); & $b *> $null; $sw.Stop()
  "{0,-46} {1,7:N2}s" -f $label, $sw.Elapsed.TotalSeconds
}

"--- startup layers (3 runs each)"
1..3 | ForEach-Object { Time-It 'node.exe --version' { & $node --version } }
1..3 | ForEach-Object { Time-It 'node.exe codegraph.js --version' { & $node --liftoff-only --disable-warning=ExperimentalWarning $cli --version } }
1..3 | ForEach-Object { Time-It 'codegraph.cmd --version' { & (Join-Path $bundle 'bin\codegraph.cmd') --version } }
1..2 | ForEach-Object { Time-It 'node.exe codegraph.js status (django)' { & $node --liftoff-only --disable-warning=ExperimentalWarning $cli status $proj } }

"--- incremental sync on django"
$py = Get-ChildItem (Join-Path $proj 'django') -Recurse -Filter *.py | Select-Object -First 60
$i = 0
foreach ($n in 1, 5, 50) {
  $batch = $py | Select-Object -Skip $i -First $n
  $i += $n
  foreach ($f in $batch) { Add-Content $f.FullName "`n# spike-edit`ndef spike_fn_$([guid]::NewGuid().ToString('N'))():`n    return 1`n" }
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $out = & $node --liftoff-only --disable-warning=ExperimentalWarning $cli sync $proj 2>&1 | Out-String
  $sw.Stop()
  $line = ($out -split "`n" | Where-Object { $_ -match 'Modified|Resolved' }) -join ' | '
  "{0,3} files changed -> sync wall {1,7:N2}s   {2}" -f $n, $sw.Elapsed.TotalSeconds, $line.Trim()
}
"--- no-op sync"
Time-It 'sync, nothing changed' { & $node --liftoff-only --disable-warning=ExperimentalWarning $cli sync $proj }
