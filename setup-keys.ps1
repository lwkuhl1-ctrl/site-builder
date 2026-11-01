# Saves the Site Builder's API keys for this Windows user (outside OneDrive). Keys are typed hidden.
function Save-Key($name, $label, $hint) {
    $have = -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, 'User'))
    Write-Host ""
    Write-Host "$label" -ForegroundColor Cyan
    Write-Host "  $hint"
    if ($have) { Write-Host "  Already saved. Press Enter to keep it, or paste a new one." -ForegroundColor DarkGray }
    $secure = Read-Host "  Paste key (it stays hidden)" -AsSecureString
    $value = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)).Trim().Trim('"')
    if ([string]::IsNullOrWhiteSpace($value)) {
        if ($have) { Write-Host "  Kept the saved key." -ForegroundColor Green } else { Write-Host "  Skipped." -ForegroundColor Yellow }
        return
    }
    [Environment]::SetEnvironmentVariable($name, $value, 'User')
    Write-Host "  Saved ($($value.Length) characters)." -ForegroundColor Green
}

Write-Host "Site Builder key setup" -ForegroundColor White
Save-Key 'ANTHROPIC_API_KEY' 'Anthropic API key (writes the website copy)' 'console.anthropic.com > API Keys. Starts with sk-ant-'
Save-Key 'PIXABAY_API_KEY' 'Pixabay API key (free stock photos)' 'pixabay.com/api/docs > "Parameters" section, the green value next to key'
Write-Host ""
Write-Host "Done. Close the Site Builder window if it's open and start it again." -ForegroundColor White
