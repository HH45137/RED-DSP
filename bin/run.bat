@echo on
set "batdir=%~dp0"

if "%~1"=="" (
    echo Usage: %~nx0 ^<C_source_file_path^>
    exit /b 1
)

set "infile=%~f1"
set "outfile=%batdir%%~n1.s"

echo Input file: %infile%
echo Output assembly: %outfile%

REM Step 1: Generate assembly from C
python "%batdir%..\emu\gen_asm_form_c.py" "%infile%" -o "%outfile%"
if errorlevel 1 exit /b 1

REM Step 2: Run the emulator to see results
python "%batdir%..\emu\red_dsp_emu.py" "%outfile%" --isa "%batdir%..\emu\isa.csv"
if errorlevel 1 exit /b 1

echo All steps completed successfully.
pause