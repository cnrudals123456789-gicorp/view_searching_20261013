# 작업 스케줄러 '뷰성형외과 조회요청 확인' 등록 (2분마다 GitHub 의 docs/request.json 확인)
# 공개 페이지에서 [조회 요청]이 들어오면 이 PC 가 순위를 조회하고 웹에 게시한다. (poll_request.py)
# 실행: powershell -ExecutionPolicy Bypass -File .\조회요청확인_등록.ps1
# 매일 10:10·16:00 자동 조회는 별도 (작업스케줄러_등록.ps1)
$dir = $PSScriptRoot
$py = (Get-Command python).Source
$action = New-ScheduledTaskAction -Execute $py -Argument "-I `"$dir\poll_request.py`"" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 2)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "뷰성형외과 조회요청 확인" -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "등록 완료: 2분마다 조회 요청 확인 -> $dir\poll_request.py"
Write-Host "※ 이 PC 가 켜져 있고 절전이 아니어야 요청이 처리됩니다."
