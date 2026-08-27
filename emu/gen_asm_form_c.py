from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_ISA_PATH = ROOT_DIR / "../emu" / "isa.csv"
DEFAULT_LLC_PATH = ROOT_DIR / "../llvm-build-reddsp" / "bin" / "llc.exe"


def find_clang() -> str:
    configured = os.environ.get("REDDSP_CLANG")
    if configured:
        return configured

    clang = shutil.which("clang")
    if clang:
        return clang

    raise FileNotFoundError(
        "找不到 clang。请设置 REDDSP_CLANG 环境变量，"
        "或通过 --clang 指定 clang.exe 路径。"
    )


def find_llc() -> Path:
    configured = os.environ.get("REDDSP_LLC")
    path = Path(configured) if configured else DEFAULT_LLC_PATH
    if not path.is_file():
        raise FileNotFoundError(
            f"找不到 RED DSP llc：{path}。" "请先构建 LLVM，或通过 --llc 指定路径。"
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
        raise FileNotFoundError(f"输入文件不存在：{input_path}")
    if input_path.suffix.lower() != ".c":
        raise ValueError(f"输入文件必须使用 .c 扩展名：{input_path}")
    if not isa_path.is_file():
        raise FileNotFoundError(f"ISA CSV 不存在：{isa_path}")

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

        print(f"生成成功：{output_path}")
        print(
            f"指令数：{analysis.metrics['instruction_count']}，"
            f"Bundle 数：{analysis.metrics['bundle_count']}"
        )

        if keep_intermediate:
            print(f"LLVM IR：{ir_path}")
            print(f"线性汇编：{linear_path}")
        else:
            linear_path.unlink(missing_ok=True)
    finally:
        if temporary_directory is not None:
            temporary_directory.cleanup()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="将 C 文件编译为 RED DSP VLIW 汇编文件"
    )
    parser.add_argument("input", type=Path, help="输入的 .c 文件")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="输出的 .s 文件，默认与输入文件同名",
    )
    parser.add_argument(
        "-O",
        "--optimization",
        choices=("0", "1", "2", "3", "s"),
        default="2",
        help="Clang 优化级别，默认 -O2",
    )
    parser.add_argument(
        "--clang",
        default=None,
        help="clang.exe 路径，也可以通过 REDDSP_CLANG 设置",
    )
    parser.add_argument(
        "--llc",
        type=Path,
        default=None,
        help="RED DSP llc.exe 路径，也可以通过 REDDSP_LLC 设置",
    )
    parser.add_argument(
        "--isa",
        type=Path,
        default=DEFAULT_ISA_PATH,
        help=f"ISA CSV 路径，默认：{DEFAULT_ISA_PATH}",
    )
    parser.add_argument(
        "--keep-intermediate",
        action="store_true",
        help="保留 .ll 和 .linear.s 中间文件",
    )
    parser.add_argument(
        "--ir-output",
        type=Path,
        help="指定 LLVM IR 输出路径",
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
        print(f"命令执行失败，退出码：{error.returncode}", file=sys.stderr)
        raise SystemExit(error.returncode)
    except (FileNotFoundError, OSError, ValueError) as error:
        print(f"错误：{error}", file=sys.stderr)
        raise SystemExit(1)
