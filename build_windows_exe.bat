@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo 环形拼接件 DXF 生成器 - Windows 构建
echo ========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo 未找到 Python。构建电脑需要先安装 Python 3。
    echo 下载地址：https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

echo 正在安装或更新 PyInstaller...
py -3 -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo PyInstaller 安装失败。
    pause
    exit /b 1
)

echo 正在构建 EXE，请稍候...
py -3 -m PyInstaller --clean --noconfirm --onedir --windowed --name "环形拼接件生成器" ring_generator_gui.py
if errorlevel 1 (
    echo 构建失败。
    pause
    exit /b 1
)

echo.
echo 构建完成：
echo dist\环形拼接件生成器\环形拼接件生成器.exe
echo.
echo 将整个 dist\环形拼接件生成器 文件夹复制到目标 Windows 电脑即可运行。
pause
