# Shows whether the Site Builder's API keys are saved for your Windows user. Never prints the keys.
foreach ($n in 'ANTHROPIC_API_KEY', 'PIXABAY_API_KEY') {
    $v = [Environment]::GetEnvironmentVariable($n, 'User')
    if ([string]::IsNullOrWhiteSpace($v)) { Write-Host "$n : NOT SAVED" -ForegroundColor Red }
    else { Write-Host "$n : saved ($($v.Length) characters)" -ForegroundColor Green }
}
