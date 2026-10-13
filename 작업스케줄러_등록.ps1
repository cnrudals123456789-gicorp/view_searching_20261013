# 작업 스케줄러 '뷰성형외과 순위체크+게시' 등록 (매일 10:10 · 16:00, 창 없이 실행)
# 실행: powershell -ExecutionPolicy Bypass -File .\작업스케줄러_등록.ps1
# 원본 패키지의 작업스케줄러_등록.ps1 과 같은 설정이며, 실행 대상만 '자동실행_및_게시.bat' (순위 체크 후 웹 게시)
$dir = $PSScriptRoot
$bat = Join-Path $dir "자동실행_및_게시.bat"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"& '$bat'`"" `
    -WorkingDirectory $dir
$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At "10:10"),
    (New-ScheduledTaskTrigger -Daily -At "16:00")
)
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "뷰성형외과 순위체크+게시" -Action $action -Trigger $triggers -Settings $settings -Force
Write-Host "등록 완료: 매일 10:10 / 16:00 -> $bat"
Write-Host "※ 절전 중 자동 기상: powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1 (DC 도 동일) 후 powercfg /setactive SCHEME_CURRENT"
