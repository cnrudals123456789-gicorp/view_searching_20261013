# 작업 스케줄러 '뷰성형외과 순위체크+게시' 등록 (매일 10:10 · 16:10, 창 없이 실행)
# 실행: powershell -ExecutionPolicy Bypass -File .\작업스케줄러_등록.ps1
# 동작: 순위 조회(run_and_publish.bat) → docs\data.json 갱신 → GitHub 푸시 → 공개 링크 자동 반영
# - PC 가 시각에 꺼져 있었다면 켜진 직후 바로 실행(StartWhenAvailable), 두 번이 겹치면 뒤의 것은 건너뜀
# - 이 PC 는 Windows 에 로그인된 상태여야 한다 (사용자 계정으로 실행)
$dir = $PSScriptRoot
$bat = Join-Path $dir "run_and_publish.bat"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"& '$bat'`"" `
    -WorkingDirectory $dir
$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At "10:10"),
    (New-ScheduledTaskTrigger -Daily -At "16:10")
)
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "뷰성형외과 순위체크+게시" -Action $action -Trigger $triggers -Settings $settings -Force
Write-Host "등록 완료: 매일 10:10 / 16:10 -> $bat"

# '뷰성형외과 네이버 주간 로그인' (매주 월요일 09:40): 로그아웃 후 로그인 창을 띄워 직접 로그인 (최대 25분 대기)
# 자동 로그인은 캡차 등으로 실패하면 멈추고, 직접 로그인 후 7일이 지나면 쓰지 않는다 (naver_guard.py)
$guard = Join-Path $dir "naver_guard.py"
$wAction = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"`$env:PYTHONUTF8=1; python '$guard' weekly *>> '$dir\logs\guard.log'`"" `
    -WorkingDirectory $dir
$wSettings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 40) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "뷰성형외과 네이버 주간 로그인" -Action $wAction `
    -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "09:40") -Settings $wSettings -Force
Write-Host "등록 완료: 매주 월요일 09:40 -> 네이버 직접 로그인 창"
Write-Host "※ PC 가 낮 동안 절전에 들어가지 않게: powercfg /change standby-timeout-ac 0  /  powercfg /change standby-timeout-dc 0"
