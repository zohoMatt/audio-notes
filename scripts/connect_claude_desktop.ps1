# Adds the audio-notes MCP server to the Microsoft Store build of Claude Desktop.
# Run this while Claude Desktop is FULLY QUIT (it rewrites its config file when it exits).
param([string]$Exe = "D:\Coding\audio-notes\dist\audio-notes\audio-notes.exe")
$ErrorActionPreference = "Stop"
if (Get-Process claude -ErrorAction SilentlyContinue) { throw "Claude Desktop is still running. Quit it (also from the tray) and run this again." }
$p = Get-ChildItem "$env:LOCALAPPDATA\Claude-Data\claude_*\claude_desktop_config.json" | Select-Object -First 1 -ExpandProperty FullName
if (-not $p) { throw "claude_desktop_config.json not found under $env:LOCALAPPDATA\Claude-Data" }
Copy-Item $p "$p.bak-audio-notes" -Force
$t = [IO.File]::ReadAllText($p)
if ($t -match '"mcpServers"') { throw "mcpServers already present in $p; edit it by hand." }
$esc = $Exe.Replace('\', '\\')
$ins = "{`n  `"mcpServers`": {`n    `"audio-notes`": {`n      `"command`": `"$esc`",`n      `"args`": [`"mcp`"]`n    }`n  },"
$t = $ins + $t.Substring($t.IndexOf('{') + 1)
[IO.File]::WriteAllText($p, $t, (New-Object Text.UTF8Encoding $false))
Get-Content $p -Raw | ConvertFrom-Json | Out-Null   # throws if the JSON is broken
Write-Host "OK: audio-notes added to $p. Now start Claude Desktop."
