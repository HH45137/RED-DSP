import struct
from typing import List, Tuple, Optional
import csv


class Instruction:
    # One decoded instruction.
    TYPE: str
    OP: str
    DST: str
    SRC1: str
    SRC2: str
    IMM: str

    def __init__(
        self, _TYPE: str, _OP: str, _DST: str, _SRC1: str, _SRC2: str, _IMM: str
    ):
        self.TYPE = _TYPE
        self.OP = _OP
        self.DST = _DST
        self.SRC1 = _SRC1
        self.SRC2 = _SRC2
        self.IMM = _IMM

    @classmethod
    def nop(cls):
        # Empty instruction used to fill unused slots.
        return cls(
            _TYPE="NOP",
            _OP="NOP",
            _DST="X",
            _SRC1="X",
            _SRC2="X",
            _IMM="X",
        )


class InstructionBundle:
    # A bundle has four fixed execution slots.
    bundle = {
        "ALU0": Instruction,
        "ALU1": Instruction,
        "SFU0": Instruction,
        "LSU0": Instruction,
    }

    def __init__(
        self,
        _Inst0: Instruction,
        _Inst1: Instruction,
        _Inst2: Instruction,
        _Inst3: Instruction,
    ):
        # Keep the slot names used by the DSP layout.
        self.bundle = {
            "ALU0": _Inst0,
            "ALU1": _Inst1,
            "SFU0": _Inst2,
            "LSU0": _Inst3,
        }


class RedDSP:
    bundles = []

    def __init__(self):
        self.bundles = []

    def run(self, _AsmPath: str, _IsaPath: str):
        # Load the ISA table and the assembly source.
        isa_define = self.parser_isa(_IsaPath)

        asm_words = self.load_program(_Path=_AsmPath)

        self.parser(_AsmWords=asm_words, _IsaDefine=isa_define)

        # Show the decoded bundles for now.
        for index, bundle in enumerate(self.bundles):
            ops = [instruction.OP for instruction in bundle.bundle.values()]
            print(f"Bundle {index}: {ops}")

    def load_program(self, _Path: str):
        # Read non-empty assembly lines and remove comments.
        words = []
        with open(_Path, "r", encoding="utf-8") as f:
            for line in f:
                if "//" in line:
                    line = line.split("//", 1)[0]
                parts = line.split()
                if len(parts) != 0:
                    words.extend([parts])
        # print(words)
        return words

    def parser_isa(self, _IsaPath: str):
        # Load instruction definitions from the CSV file.
        table = []
        with open(_IsaPath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            table = list(reader)

        return table

        # Start fresh when the same emulator is run more than once.

    def parser(self, _AsmWords, _IsaDefine):
        self.bundles.clear()
        # Map each opcode to its ISA definition for quick lookup.

        isa_by_opcode = {
            isa_definition["OP"]: isa_definition
            for isa_definition in _IsaDefine
            # Put one source instruction in one bundle.
            # This keeps dependent instructions in program order.
        }

        for source_line in _AsmWords:
            opcode = source_line[0]
            isa_definition = isa_by_opcode.get(opcode)
            if isa_definition is None:
                raise ValueError(f"Unknown opcode: {opcode}")

            instruction = Instruction(
                _TYPE=isa_definition["TYPE"],
                _OP=isa_definition["OP"],
                _DST=source_line[1] if len(source_line) > 1 else "X",
                _SRC1=source_line[2] if len(source_line) > 2 else "X",
                _SRC2=source_line[3] if len(source_line) > 3 else "X",
                _IMM=source_line[4] if len(source_line) > 4 else "X",
            )

            # The real instruction uses ALU0; the other slots are NOPs.
            self.bundles.append(
                InstructionBundle(
                    _Inst0=instruction,
                    _Inst1=Instruction.nop(),
                    _Inst2=Instruction.nop(),
                    _Inst3=Instruction.nop(),
                )
            )


if __name__ == "__main__":
    dsp = RedDSP()

    dsp.run("emu/asm/helloworld.s", "emu/isa.csv")
