param(
    [ValidateSet('install', 'remove', 'status')][string]$Action = 'status',
    [string]$CodePath = '',
    [string]$RegistryRoot = 'Software\Classes'
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$owner = 'a8devtools.bgin-editor'
$progId = 'A8DevTools.BinaryGin'
$hive = [Microsoft.Win32.Registry]::CurrentUser

function Open-Key([string]$Suffix, [bool]$Write = $false) {
    return $hive.OpenSubKey("$RegistryRoot\$Suffix", $Write)
}
function Set-Value([string]$Suffix, [string]$Name, [string]$Value) {
    $key = $hive.CreateSubKey("$RegistryRoot\$Suffix")
    try { $key.SetValue($Name, $Value, [Microsoft.Win32.RegistryValueKind]::String) }
    finally { $key.Dispose() }
}
function Remove-Value([string]$Suffix, [string]$Name, [string]$Expected) {
    $key = Open-Key $Suffix $true
    if ($null -eq $key) { return }
    try {
        if ($key.GetValue($Name, $null) -ceq $Expected) { $key.DeleteValue($Name, $false) }
        $empty = $key.ValueCount -eq 0 -and $key.SubKeyCount -eq 0
    } finally { $key.Dispose() }
    if ($empty) { $hive.DeleteSubKey("$RegistryRoot\$Suffix", $false) }
}

try {
    $shell = Open-Key '.bgin\ShellNew'
    $managed = $null -ne $shell -and $shell.GetValue('BginEditorOwner', '') -ceq $owner
    $hasNull = $null -ne $shell -and $shell.GetValueNames() -contains 'NullFile'
    $hasOther = $null -ne $shell -and @($shell.GetValueNames() | Where-Object { $_ -in @('Command', 'Data', 'FileName') }).Count -gt 0
    if ($null -ne $shell) { $shell.Dispose() }

    if ($Action -eq 'install') {
        if ($hasOther -and -not $managed) { throw 'Another application has registered BGIN creation. Its settings were preserved.' }
        if (-not $hasNull -or $managed) {
            $extension = Open-Key '.bgin'
            $association = if ($extension) { $extension.GetValue('', '') } else { '' }
            if ($extension) { $extension.Dispose() }
            if (-not $association -and $RegistryRoot -eq 'Software\Classes') {
                $merged = [Microsoft.Win32.Registry]::ClassesRoot.OpenSubKey('.bgin')
                if ($merged) { $association = $merged.GetValue('', ''); $merged.Dispose() }
            }
            if (-not $association) {
                if (-not (Test-Path -LiteralPath $CodePath -PathType Leaf)) { throw 'VS Code executable was not found.' }
                Set-Value $progId '' 'Binary GIN'
                Set-Value $progId 'BginEditorOwner' $owner
                Set-Value "$progId\DefaultIcon" '' ('"' + $CodePath + '",0')
                Set-Value "$progId\shell\open\command" '' ('"' + $CodePath + '" --reuse-window "%1"')
                Set-Value '.bgin' '' $progId
                Set-Value '.bgin' 'BginEditorAssociationOwner' $owner
            }
            Set-Value '.bgin\ShellNew' 'BginEditorOwner' $owner
            Set-Value '.bgin\ShellNew' 'NullFile' ''
        }
    } elseif ($Action -eq 'remove' -and $managed) {
        Remove-Value '.bgin\ShellNew' 'NullFile' ''
        Remove-Value '.bgin\ShellNew' 'BginEditorOwner' $owner
        # Keep the file association: existing BGIN files should still open in
        # VS Code after the user disables only Explorer's New menu entry.
    }

    if ($Action -ne 'status' -and $RegistryRoot -eq 'Software\Classes') {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class BginShellNotify {
    [DllImport("shell32.dll")]
    public static extern void SHChangeNotify(uint e, uint flags, IntPtr a, IntPtr b);
}
'@
        [BginShellNotify]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
    }
    $shell = Open-Key '.bgin\ShellNew'
    $enabled = $null -ne $shell -and $shell.GetValueNames() -contains 'NullFile'
    $managed = $null -ne $shell -and $shell.GetValue('BginEditorOwner', '') -ceq $owner
    if ($shell) { $shell.Dispose() }
    @{ enabled = $enabled; managed = $managed } | ConvertTo-Json -Compress
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
