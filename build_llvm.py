#!/usr/bin/env python3
"""
build_llvm.py - Minimal CMake wrapper to build LLVM with RedDSP backend.
CMake auto-detects compiler, Ninja is required.
"""

import os
import sys
import shutil
import subprocess
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Build LLVM RedDSP backend")
    parser.add_argument("--source", default="llvm/llvm", help="LLVM source dir")
    parser.add_argument("--build", default="llvm-build-reddsp", help="Build dir")
    parser.add_argument("--output", default="bin", help="Output dir for binaries")
    parser.add_argument("--build-type", default="RelWithDebInfo", help="Build type")
    parser.add_argument("--jobs", type=int, default=0, help="Parallel jobs (0=auto)")
    args = parser.parse_args()

    root = Path(__file__).parent.resolve()
    src = root / args.source
    build = root / args.build
    out = root / args.output
    jobs = args.jobs if args.jobs > 0 else os.cpu_count() or 1

    # Common CMake arguments (let CMake find compiler)
    cmake_args = [
        "-G",
        "Ninja",
        "-S",
        str(src),
        "-B",
        str(build),
        "-DLLVM_TARGETS_TO_BUILD=RedDSP",
        f"-DCMAKE_BUILD_TYPE={args.build_type}",
        "-DLLVM_ENABLE_RTTI=ON",
        "-DLLVM_ENABLE_ZLIB=OFF",
    ]
    if sys.platform == "win32":
        cmake_args.append("-DLLVM_ENABLE_PDB=ON")

    print(f"Source: {src}")
    print(f"Build:  {build}")
    print(f"Output: {out}")
    print(f"Type:   {args.build_type}")
    print(f"Jobs:   {jobs}")
    print()

    # Configure
    print("[1/3] Configuring CMake ...")
    subprocess.run(["cmake"] + cmake_args, check=True)

    # Build targets
    targets = ["llc", "FileCheck", "llvm-tblgen", "llvm-min-tblgen"]
    print(f"[2/3] Building {', '.join(targets)} ...")
    subprocess.run(
        ["cmake", "--build", str(build), "--config", args.build_type, "--target"]
        + targets
        + ["--", "-j", str(jobs)],
        check=True,
    )

    # Copy outputs
    print(f"[3/3] Copying binaries to {out}")
    out.mkdir(parents=True, exist_ok=True)
    bin_src = build / "bin"
    ext = ".exe" if sys.platform == "win32" else ""
    for tool in targets:
        exe = bin_src / f"{tool}{ext}"
        if exe.exists():
            shutil.copy2(exe, out)
        pdb = bin_src / f"{tool}.pdb"
        if pdb.exists():
            shutil.copy2(pdb, out)
    for lit in ["llvm-lit.py", "llvm-lit.cmd"]:
        f = bin_src / lit
        if f.exists():
            shutil.copy2(f, out)

    print("\n=== Build complete ===")
    print(f"Binaries in: {out}")


if __name__ == "__main__":
    main()
