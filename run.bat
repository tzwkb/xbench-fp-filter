@echo off
cd /d "%~dp0"

if exist python\python.exe (
    set PY=python\python.exe
) else (
    where python >nul 2>nul
    if not errorlevel 1 (
        set PY=python
    ) else (
        echo [run.bat] 未检测到 Python，正在自动运行 setup.bat...
        call setup.bat
        if errorlevel 1 (
            pause & exit /b 1
        )
        set PY=python\python.exe
    )
)

if not exist config.py (
    echo 配置文件 config.py 不存在，请先填写 API Key。
    echo 参考：copy config_template.py config.py 并编辑。
    pause & exit /b 1
)

%PY% -m streamlit run app.py --browser.gatherUsageStats false
pause
