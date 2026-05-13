@echo off
cd /d "%~dp0"
echo 正在启动特别想-Lab 测试后台...
echo.
echo 如果看到 TBX test backend running on http://0.0.0.0:8000 就说明启动成功。
echo 这个窗口不要关闭，关闭后小程序会提示网络连接失败。
echo.
python simple_mp_server.py
pause
