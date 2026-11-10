@echo off
chcp 65001 >nul
rem ================================================================
rem  Сборка Синевы+ в Sineva.exe. Запускать из КОРНЯ проекта (рядом с sp.py).
rem    build_exe.bat           - меню
rem    build_exe.bat full      - полный вариант (с MiniLM / PM)
rem    build_exe.bat compact   - компактный (без MiniLM и лишнего)
rem    build_exe.bat all       - оба подряд
rem  Результат: dist\Sineva_full\Sineva.exe и dist\Sineva_compact\Sineva.exe
rem ================================================================
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller не найден, ставлю...
    python -m pip install pyinstaller
    if errorlevel 1 goto :fail
)

set CHOICE=%1
if not "%CHOICE%"=="" goto :run

echo.
echo   1 - полный  ^(с MiniLM / PM, большой^)
echo   2 - компактный ^(без MiniLM и лишнего^)
echo   3 - оба
echo.
set /p N=Что собрать [1/2/3]: 
if "%N%"=="1" set CHOICE=full
if "%N%"=="2" set CHOICE=compact
if "%N%"=="3" set CHOICE=all
if "%CHOICE%"=="" goto :usage

:run
if /i "%CHOICE%"=="full"    call :build full    || goto :fail
if /i "%CHOICE%"=="compact" call :build compact || goto :fail
if /i "%CHOICE%"=="all"     call :build full    || goto :fail
if /i "%CHOICE%"=="all"     call :build compact || goto :fail
echo.
echo Готово. Смотрите папку dist\
pause
exit /b 0

:build
echo.
echo ===== Сборка: %1 =====
set SINEVA_VARIANT=%1
python -m PyInstaller --noconfirm --clean --distpath "dist" --workpath "build\%1" sineva.spec
exit /b %errorlevel%

:usage
echo Использование: build_exe.bat [full^|compact^|all]
pause
exit /b 1

:fail
echo.
echo СБОРКА НЕ УДАЛАСЬ - смотрите сообщения выше.
pause
exit /b 1
