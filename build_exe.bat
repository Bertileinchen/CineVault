@echo off
REM Baut eine eigenstaendige CineVault.exe (nur unter Windows ausfuehren,
REM nachdem "pip install -r requirements.txt" gelaufen ist).
setlocal

REM "python" ist nicht auf jedem Windows-Rechner im PATH (haengt von der
REM Installationsart ab) -- auf den offiziellen "py"-Launcher ausweichen,
REM falls "python" nicht gefunden wird.
where python >nul 2>&1
if errorlevel 1 (
    set PYCMD=py
) else (
    set PYCMD=python
)

echo Verwende: %PYCMD%
%PYCMD% --version
echo.

REM WICHTIG: bewusst "%PYCMD% -m PyInstaller" statt einfach "pyinstaller"
REM aufrufen. pip installiert PyInstaller zwar korrekt, aber die dabei
REM erzeugte pyinstaller.exe landet in einem "Scripts"-Ordner, der je nach
REM Windows-/Python-Installation NICHT automatisch im PATH liegt -- das ist
REM die haeufigste Ursache fuer "pyinstaller wird nicht gefunden", obwohl
REM die Installation an sich funktioniert hat. Der Aufruf ueber "-m" nutzt
REM stattdessen direkt die Python-Installation, in der PyInstaller
REM installiert ist, unabhaengig vom PATH.
%PYCMD% -m PyInstaller --version
if errorlevel 1 (
    echo.
    echo FEHLER: PyInstaller wurde nicht gefunden ^(siehe Meldung oben^).
    echo.
    echo Bitte in dieser Konsole zuerst ausfuehren:
    echo     %PYCMD% -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo.
echo Baue CineVault.exe ...
echo.

%PYCMD% -m PyInstaller --noconfirm --windowed --onefile --name CineVault ^
    --icon=assets\cinevault.ico ^
    --add-data "assets;assets" ^
    main.py

if errorlevel 1 (
    echo.
    echo ============================================================
    echo FEHLER: Der Build ist fehlgeschlagen ^(siehe Meldungen oben^).
    echo Bitte die komplette Ausgabe oben kopieren.
    echo ============================================================
    echo.
    pause
    exit /b 1
)

if not exist "dist\CineVault.exe" (
    echo.
    echo ============================================================
    echo WARNUNG: Kein Fehler gemeldet, aber dist\CineVault.exe fehlt
    echo trotzdem. Bitte die komplette Ausgabe oben kopieren.
    echo ============================================================
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Fertig! Die exe liegt in dist\CineVault.exe
echo ============================================================
pause
