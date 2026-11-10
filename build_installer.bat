@echo off
chcp 65001 >nul
rem ================================================================
rem  Сборка установщиков Синевы+ (нужен Inno Setup 6: https://jrsoftware.org/isinfo.php).
rem  Запускать из КОРНЯ проекта, ПОСЛЕ build_exe.bat.
rem    build_installer.bat           - меню
rem    build_installer.bat full      - установщик полного варианта
rem    build_installer.bat compact   - установщик компактного варианта
rem    build_installer.bat all       - оба
rem  Результат: installer\Sineva_Setup_full_<версия>.exe, installer\Sineva_Setup_compact_<версия>.exe
rem ================================================================
cd /d "%~dp0"

set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe
if "%ISCC%"=="" (
    echo Inno Setup 6 не найден. Установите его с https://jrsoftware.org/isdl.php и запустите снова.
    goto :fail
)

rem Версия берётся из sp.py (строка APP_VERSION = "1.0.0").
set VER=1.0.0
for /f "delims=" %%l in ('findstr /b /c:"APP_VERSION" sp.py') do set LINE=%%l
if defined LINE set LINE=%LINE:*"=%
if defined LINE set VER=%LINE:"=%
echo Версия: %VER%

set CHOICE=%1
if not "%CHOICE%"=="" goto :run

echo.
echo   1 - установщик полного варианта
echo   2 - установщик компактного варианта
echo   3 - оба
echo.
set /p N=Что собрать [1/2/3]: 
if "%N%"=="1" set CHOICE=full
if "%N%"=="2" set CHOICE=compact
if "%N%"=="3" set CHOICE=all
if "%CHOICE%"=="" goto :usage

:run
if /i "%CHOICE%"=="full"    call :make full    || goto :fail
if /i "%CHOICE%"=="compact" call :make compact || goto :fail
if /i "%CHOICE%"=="all"     call :make full    || goto :fail
if /i "%CHOICE%"=="all"     call :make compact || goto :fail
echo.
echo Готово. Смотрите папку installer\
pause
exit /b 0

:make
if not exist "dist\Sineva_%1\Sineva.exe" (
    echo Нет dist\Sineva_%1\Sineva.exe - сначала выполните build_exe.bat %1
    exit /b 1
)
echo.
echo ===== Установщик: %1 =====
"%ISCC%" /Qp /DVariant=%1 /DAppVersion=%VER% sineva.iss
exit /b %errorlevel%

:usage
echo Использование: build_installer.bat [full^|compact^|all]
pause
exit /b 1

:fail
echo.
echo СБОРКА НЕ УДАЛАСЬ - смотрите сообщения выше.
pause
exit /b 1
