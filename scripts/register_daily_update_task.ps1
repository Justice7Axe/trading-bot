# 일봉 일일 업데이트를 Windows 작업 스케줄러에 등록 (평일 20:00)
#   등록:  powershell -ExecutionPolicy Bypass -File scripts\register_daily_update_task.ps1
#   해제:  Unregister-ScheduledTask -TaskName "EllieTrading_DailyUpdate" -Confirm:$false
#   수동 실행: Start-ScheduledTask -TaskName "EllieTrading_DailyUpdate"
param(
    [string]$Time = "20:00"
)

$TaskName = "EllieTrading_DailyUpdate"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "가상환경 python을 찾을 수 없습니다: $Python"
}

# 창 없이 실행 (2026-11-17 사용자 '그것도 창 없이'): python.exe 를 바로 띄우면 콘솔 창이 뜸 → conhost --headless 로 감싸고
# 화면 출력은 data\logs\daily_update_task.log 로. PYTHONIOENCODING=utf-8 은 출력 파일에 한글·이모지 쓰기용(파일 읽기 기본 인코딩은 그대로).
$action = New-ScheduledTaskAction `
    -Execute "$env:WINDIR\System32\conhost.exe" `
    -Argument "--headless cmd.exe /c `"set PYTHONIOENCODING=utf-8&& .venv\Scripts\python.exe -m kiwoom_trading.ingestion.run_daily_update >> data\logs\daily_update_task.log 2>&1`"" `
    -WorkingDirectory $ProjectRoot

$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $Time

# WakeToRun: 절전 중이면 20:00에 PC를 깨워서 실행 (실행 중 절전 방지는 스크립트가 직접 처리)
# StartWhenAvailable: 20:00에 PC가 꺼져 있었으면 다음에 켜질 때 실행
$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description "Ellie trading: 국내주식 일봉 일일 업데이트 (kiwoom_trading.ingestion.run_daily_update)" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo | Select-Object TaskName, NextRunTime
