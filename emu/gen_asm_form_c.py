from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_ISA_PATH = ROOT_DIR / "../doc" / "isa.csv"
DEFAULT_LLC_PATH = ROOT_DIR / "../bin" / "llc.exe"


def find_clang() -> str:
    configured = os.environ.get("REDDSP_CLANG")
    if configured:
        return configured

    clang = shutil.which("clang")
    if clang:
        return clang

    raise FileNotFoundError(
        "Could not find clang. Set the REDDSP_CLANG environment variable "
        "or specify the clang.exe path with --clang."
    )


def find_llc() -> Path:
    configured = os.environ.get("REDDSP_LLC")
    path = Path(configured) if configured else DEFAULT_LLC_PATH
    if not path.is_file():
        raise FileNotFoundError(
            f"Could not find the RED DSP llc: {path}. "
            "Build LLVM first, or specify the path with --llc."
        )
    return path


def run_command(command: list[str]) -> None:
    print("+", subprocess.list2cmdline(command))
    subprocess.run(command, check=True)


def load_optimizer(isa_path: Path):
    sys.path.insert(0, str(isa_path.parent))
    from red_dsp_asm_opti import analyze_assembly

    return analyze_assembly


def compile_c(
    input_path: Path,
    output_path: Path,
    clang: str,
    llc: Path,
    isa_path: Path,
    optimization_level: str,
    keep_intermediate: bool,
    ir_output: Path | None,
) -> None:
    input_path = input_path.resolve()
    output_path = output_path.resolve()
    isa_path = isa_path.resolve()

    if not input_path.is_file():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")
    if input_path.suffix.lower() != ".c":
        raise ValueError(f"Input file must have a .c extension: {input_path}")
    if not isa_path.is_file():
        raise FileNotFoundError(f"ISA CSV does not exist: {isa_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    linear_path = output_path.with_suffix(".linear.s")
    temporary_directory: tempfile.TemporaryDirectory[str] | None = None

    if ir_output is not None:
        ir_path = ir_output.resolve()
        ir_path.parent.mkdir(parents=True, exist_ok=True)
    elif keep_intermediate:
        ir_path = output_path.with_suffix(".ll")
    else:
        temporary_directory = tempfile.TemporaryDirectory()
        ir_path = Path(temporary_directory.name) / f"{input_path.stem}.ll"

    try:
        run_command(
            [
                clang,
                "-S",
                "-emit-llvm",
                f"-O{optimization_level}",
                str(input_path),
                "-o",
                str(ir_path),
            ]
        )

        run_command(
            [
                str(llc),
                "-mtriple=reddsp-unknown-none",
                "-filetype=asm",
                str(ir_path),
                "-o",
                str(linear_path),
            ]
        )

        analyze_assembly = load_optimizer(isa_path)
        linear_assembly = linear_path.read_text(encoding="utf-8")
        analysis = analyze_assembly(linear_assembly, isa_path)
        output_path.write_text(analysis.assembly, encoding="utf-8")

        print(f"Generated successfully: {output_path}")
        print(
            f"Instruction count: {analysis.metrics['instruction_count']}, "
            f"Bundle count: {analysis.metrics['bundle_count']}"
        )

        if keep_intermediate:
            print(f"LLVM IR: {ir_path}")
            print(f"Linear assembly: {linear_path}")
        else:
            linear_path.unlink(missing_ok=True)
    finally:
        if temporary_directory is not None:
            temporary_directory.cleanup()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compile a C file into RED DSP VLIW assembly"
    )
    parser.add_argument("input", type=Path, help="Input .c file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output .s file, defaults to the input file name",
    )
    parser.add_argument(
        "-O",
        "--optimization",
        choices=("0", "1", "2", "3", "s"),
        default="2",
        help="Clang optimization level, default -O2",
    )
    parser.add_argument(
        "--clang",
        default=None,
        help="clang.exe path; can also be set via REDDSP_CLANG",
    )
    parser.add_argument(
        "--llc",
        type=Path,
        default=None,
        help="RED DSP llc.exe path; can also be set via REDDSP_LLC",
    )
    parser.add_argument(
        "--isa",
        type=Path,
        default=DEFAULT_ISA_PATH,
        help=f"ISA CSV path, default: {DEFAULT_ISA_PATH}",
    )
    parser.add_argument(
        "--keep-intermediate",
        action="store_true",
        help="Keep the .ll and .linear.s intermediate files",
    )
    parser.add_argument(
        "--ir-output",
        type=Path,
        help="Specify the LLVM IR output path",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_path = (
        args.output.resolve() if args.output else args.input.resolve().with_suffix(".s")
    )
    clang = args.clang or find_clang()
    llc = args.llc.resolve() if args.llc else find_llc()

    compile_c(
        input_path=args.input,
        output_path=output_path,
        clang=clang,
        llc=llc,
        isa_path=args.isa,
        optimization_level=args.optimization,
        keep_intermediate=args.keep_intermediate,
        ir_output=args.ir_output,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print(f"Command failed, exit code: {error.returncode}", file=sys.stderr)
        raise SystemExit(error.returncode)
    except (FileNotFoundError, OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
