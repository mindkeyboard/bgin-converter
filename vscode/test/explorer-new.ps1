$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot '..\scripts\explorer-new.ps1'
$root = 'Software\A8DevTools\BginTests\' + [Guid]::NewGuid().ToString('N')
$classes = "$root\Classes"
$hive = [Microsoft.Win32.Registry]::CurrentUser
function Assert($Condition, $Message) { if (-not $Condition) { throw $Message } }
try {
    $code = Join-Path $PSHOME 'powershell.exe'
    $first = (& $script -Action install -CodePath $code -RegistryRoot $classes) | ConvertFrom-Json
    Assert ($first.enabled -and $first.managed) 'New menu registration failed'
    $key = $hive.OpenSubKey("$classes\.bgin\ShellNew")
    Assert ($key.GetValueNames() -contains 'NullFile') 'NullFile missing'
    $key.Dispose()
    $again = (& $script -Action install -CodePath $code -RegistryRoot $classes) | ConvertFrom-Json
    Assert $again.enabled 'Repeated install failed'
    $removed = (& $script -Action remove -RegistryRoot $classes) | ConvertFrom-Json
    Assert (-not $removed.enabled) 'Removal failed'
    $key = $hive.OpenSubKey("$classes\.bgin")
    Assert ($key.GetValue('') -eq 'A8DevTools.BinaryGin') 'Disabling New unexpectedly removed the file association'
    $key.Dispose()
    $other = "$root\Other"
    $key = $hive.CreateSubKey("$other\.bgin")
    $key.SetValue('', 'Other.ExistingBgin'); $key.SetValue('Unrelated', 'preserve'); $key.Dispose()
    $null = & $script -Action install -CodePath $code -RegistryRoot $other
    $null = & $script -Action remove -RegistryRoot $other
    $key = $hive.OpenSubKey("$other\.bgin")
    Assert ($key.GetValue('') -eq 'Other.ExistingBgin') 'Existing association overwritten'
    Assert ($key.GetValue('Unrelated') -eq 'preserve') 'Unrelated value overwritten'
    $key.Dispose()
    'BGIN_EXPLORER_TESTS: install, idempotency, removal, existing association and unrelated values passed.'
} finally {
    # This branch is a literal prefix plus a GUID created by this test only.
    if ($root -notmatch '^Software\\A8DevTools\\BginTests\\[a-f0-9]{32}$') { throw 'Unsafe test registry root' }
    $hive.DeleteSubKeyTree($root, $false)
}
