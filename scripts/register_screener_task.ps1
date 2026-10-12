# 주도주 스크리너 장중 실시간 포착을 Windows 작업 스케줄러에 등록 (평일 08:50 시작, 15:20 자동 종료)
#   등록:  powershell -ExecutionPolicy Bypass -File scripts\register_screener_task.ps1
#   해제:  Unregister-ScheduledTask -TaskName "EllieTrading_ScreenerIntraday" -Confirm:$false
#   수동 실행: Start-ScheduledTask -TaskName "EllieTrading_ScreenerIntraday"
param(
    [string]$Time = "08:50"
)

$TaskName = "EllieTrading_ScreenerIntraday"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "가상환경 python을 찾을 수 없습니다: $Python"
}

$action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "-m kiwoom_trading.screener.run_intraday" `
    -WorkingDirectory $ProjectRoot

$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $Time

# StartWhenAvailable: 08:50에 PC가 꺼져 있었으면 켜지는 즉시 시작 (15:20 이후면 스스로 종료)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 7) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description "Ellie trading: 주도주 스크리너 장중 1분 포착 (kiwoom_trading.screener.run_intraday)" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo | Select-Object TaskName, NextRunTime
