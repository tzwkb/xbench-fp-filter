@echo off
cd /d "%~dp0"
echo ============================================
echo   Xbench FP Filter - 初始化设置
echo ============================================
echo.

REM -- 步骤 1：下载内嵌 Python（已存在则跳过）--
if not exist python\python.exe (
    echo [1/3] 下载 Python 运行环境（约 10MB，需要网络）...
    powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip' -OutFile 'python_embed.zip' -UseBasicParsing"
    if errorlevel 1 (
        echo 下载失败，请检查网络连接后重试。
        pause & exit /b 1
    )
    echo 正在解压...
    powershell -Command "Expand-Archive -Path 'python_embed.zip' -DestinationPath 'python' -Force"
    del python_embed.zip
)

REM -- 步骤 1b：启用 site-packages。通配符 *.pth 匹配不到 python311._pth，必须用 python*._pth --
powershell -Command "Get-ChildItem 'python\python*._pth' | ForEach-Object { (Get-Content $_) -replace '#import site','import site' | Set-Content $_ -Encoding Ascii }"

REM -- 步骤 2：确保 pip 可用（半装环境可自愈）--
python\python.exe -m pip --version >nul 2>&1
if errorlevel 1 (
    echo 安装 pip...
    powershell -Command "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'get_pip.py' -UseBasicParsing"
    python\python.exe get_pip.py --quiet
    del get_pip.py
)

REM -- 步骤 3：安装依赖 --
echo.
echo [2/3] 安装依赖包（首次约 2-3 分钟）...
python\python.exe -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo 依赖安装失败，请检查网络连接后重试。
    pause & exit /b 1
)

REM -- 步骤 4：生成配置文件 --
echo.
echo [3/3] 检查配置文件...
if not exist config.py (
    copy config_template.py config.py >nul
    echo config.py 已生成。
) else (
    echo config.py 已存在，跳过。
)

echo.
echo ============================================
echo   设置完成！双击 run.bat 启动工具。
echo ============================================
echo.
pause
