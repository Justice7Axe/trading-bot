# 🪜 이평선 재정배열 코인 선물 모의 매매 (core.SYMBOLS: SOXLUSDT·MUUSDT) 를 Windows 작업 스케줄러에 등록 — 매일 24시간, 15분마다
#   등록:  powershell -ExecutionPolicy Bypass -File scripts\register_crypto_align_task.ps1
#   해제:  Unregister-ScheduledTask -TaskName "EllieTrading_CryptoAlign" -Confirm:$false
#   수동 실행: Start-ScheduledTask -TaskName "EllieTrading_CryptoAlign"
# 15분봉이 끝나고 40초 뒤(:00:40, :15:40, :30:40, :45:40) 실행. 한 번 돌 때 그동안 끝난 봉을 모두 판정하므로
# 24시간 거래라 절전 중이어도 15분마다 PC 를 깨워 판정함 (WakeToRun, 2026-11-15 사용자 "24시간 맞춰 항상 돌려줘").
# PC 가 완전히 꺼져 있던 동안의 봉은 켜진 뒤 첫 실행에서 몰아서 판정함 (알림에 "늦음" 표시).
$TaskName = "EllieTrading_CryptoAlign"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "가상환경 python을 찾을 수 없습니다: $Python"
}

$action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "-m kiwoom_trading.strategies.crypto_align.live" `
    -WorkingDirectory $ProjectRoot

$start = (Get-Date).Date.AddSeconds(40)
$trigger = New-ScheduledTaskTrigger -Once -At $start `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description "Ellie trading: 🪜 이평선 재정배열 코인 선물 모의 매매 SOXLUSDT·MUUSDT (kiwoom_trading.strategies.crypto_align.live)" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo | Select-Object TaskName, NextRunTime
