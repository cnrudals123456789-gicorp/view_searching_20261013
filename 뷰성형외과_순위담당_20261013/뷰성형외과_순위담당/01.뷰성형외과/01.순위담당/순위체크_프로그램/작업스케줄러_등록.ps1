# 작업 스케줄러 '파워링크 순위체크' 등록 (매일 10:10 · 16:00, 창 없이 실행)
# 실행: PowerShell 에서  powershell -ExecutionPolicy Bypass -File .\작업스케줄러_등록.ps1
# 원본 PC 설정과 동일: 절전 중 깨우기, 놓친 회차 바로 실행, 최대 8시간, 배터리여도 실행
$dir = $PSScriptRoot
$bat = Join-Path $dir "자동순위체크.bat"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"& '$bat'`"" `
    -WorkingDirectory $dir
$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At "10:10"),
    (New-ScheduledTaskTrigger -Daily -At "16:00")
)
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "파워링크 순위체크" -Action $action -Trigger $triggers -Settings $settings -Force
Write-Host "등록 완료: 매일 10:10 / 16:00 -> $bat"
Write-Host "※ 절전 중 자동 기상: 전원 옵션 '절전 모드 해제 타이머 허용'을 '사용'으로 (powercfg 로 RTCWAKE=1, AC/DC 모두)"
