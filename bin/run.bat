@echo on
REM Get the absolute path of the directory where this batch file is located
set "batdir=%~dp0"

REM Check if the C source file parameter is provided
if "%1"=="" (
    echo Usage: %~nx0 ^<C_source_file_path^>
    echo Example: %~nx0 .\examples\add_two_num.c
    exit /b 1
)

REM Convert the input C file to an absolute path
set "infile=%~f1"
REM Extract the base filename (without extension) and build the output assembly file path (in bat directory)
set "outfile=%batdir%%~n1.s"

echo Input file: %infile%
echo Output assembly: %outfile%
echo Current working directory: %cd%

REM Step 1: Generate assembly from C
python "%batdir%..\emu\gen_asm_form_c.py" "%infile%" -o "%outfile%"
if errorlevel 1 (
    echo Error: gen_asm_form_c.py failed
    exit /b 1
)

REM Step 2: Run the emulator (using space instead of equals sign for safer parsing)
python "%batdir%..\emu\red_dsp_emu.py" "%outfile%" --isa "%batdir%..\emu\isa.csv"
if errorlevel 1 (
    echo Error: red_dsp_emu.py failed
    exit /b 1
)

REM Step 3: Run the assembler optimizer (no arguments)
python "%batdir%..\emu\red_dsp_asm_opti.py"
if errorlevel 1 (
    echo Error: red_dsp_asm_opti.py failed
    exit /b 1
)

echo All steps completed successfully.
pause