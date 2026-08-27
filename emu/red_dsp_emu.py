import argparse
import csv

EXIT_VALUE = 0x01145CCB


class ExecutionLimitExceeded(RuntimeError):
    """Raised when a program does not terminate within the configured limit."""


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
    def __init__(self):
        self.bundles = []
        self.regs = [0] * 16
        self.memory = {}
        self.pc = 0
        self.isa_by_opcode = {}
        self.halted = False

    def run(self, _AsmPath: str, _IsaPath: str):
        # Load the ISA table and the assembly source.
        isa_define = self.parser_isa(_IsaPath)
        self.isa_by_opcode = {item["OP"]: item for item in isa_define}

        asm_words = self.load_program(_Path=_AsmPath)

        self.parser(_AsmWords=asm_words, _IsaDefine=isa_define)

        # Show the decoded bundles for now.
        for index, bundle in enumerate(self.bundles):
            ops = [instruction.OP for instruction in bundle.bundle.values()]
            print(f"Bundle {index}: {ops}")

    def load_program(self, _Path: str):
        # Read bundle markers and instructions, then remove comments.
        words = []
        with open(_Path, "r", encoding="utf-8") as f:
            for line in f:
                if "//" in line:
                    line = line.split("//", 1)[0]
                parts = line.split()
                if parts:
                    words.extend([parts])
        # print(words)
        return words

    def parser_isa(self, _IsaPath: str):
        # Load instruction definitions from the CSV file.
        with open(_IsaPath, "r", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def parser(self, _AsmWords, _IsaDefine):
        self.bundles.clear()
        isa_by_opcode = {item["OP"]: item for item in _IsaDefine}
        bundle_lines = None

        for source_line in _AsmWords:
            if source_line == ["{"]:
                if bundle_lines is not None:
                    raise ValueError("Nested bundle")
                bundle_lines = []
                continue
            if source_line == ["}"]:
                if bundle_lines is None:
                    raise ValueError("Bundle end without bundle start")
                self.bundles.append(self.create_bundle(bundle_lines, isa_by_opcode))
                bundle_lines = None
                continue
            if bundle_lines is None:
                raise ValueError("Instruction must be inside a bundle")
            bundle_lines.append(source_line)

        if bundle_lines is not None:
            raise ValueError("Bundle end is missing")

    def create_instruction(self, source_line, isa_by_opcode):
        opcode = source_line[0]
        isa_definition = isa_by_opcode.get(opcode)
        if isa_definition is None:
            raise ValueError(f"Unknown opcode: {opcode}")

        fields = source_line[1:]
        expected = [
            isa_definition["DST"],
            isa_definition["SRC1"],
            isa_definition["SRC2"],
            isa_definition["IMM"],
        ]
        if isa_definition["TYPE"] == "FAKE" and not fields:
            fields = ["X"] * 4
        if len(fields) != 4:
            raise ValueError(f"{opcode} expects 4 operands")
        for actual, requirement in zip(fields, expected):
            if requirement == "GR" and not self.is_register(actual):
                if opcode == "CALL" and actual.isdigit():
                    continue
                raise ValueError(f"{opcode}: expected register, got {actual}")

        return Instruction(
            _TYPE=isa_definition["TYPE"],
            _OP=isa_definition["OP"],
            _DST=fields[0],
            _SRC1=fields[1],
            _SRC2=fields[2],
            _IMM=fields[3],
        )

    def create_bundle(self, source_lines, isa_by_opcode):
        if len(source_lines) > 4:
            raise ValueError("A bundle can contain at most 4 instructions")

        slots = {
            "ALU0": Instruction.nop(),
            "ALU1": Instruction.nop(),
            "SFU0": Instruction.nop(),
            "LSU0": Instruction.nop(),
        }
        control_flow_count = 0

        for source_line in source_lines:
            instruction = self.create_instruction(source_line, isa_by_opcode)
            if instruction.OP == "NOP":
                continue
            action_name = isa_by_opcode[instruction.OP]["ACTION"].split()[0]
            if action_name in ("BEQ", "BNE", "JMP", "CALL"):
                control_flow_count += 1
            if instruction.TYPE == "ALU" or instruction.OP == "RET":
                slot = "ALU0" if slots["ALU0"].OP == "NOP" else "ALU1"
                if slots[slot].OP != "NOP":
                    raise ValueError("A bundle can contain at most 2 ALU instructions")
            elif instruction.TYPE == "SFU":
                slot = "SFU0"
                if slots[slot].OP != "NOP":
                    raise ValueError("A bundle can contain at most 1 SFU instruction")
            elif instruction.TYPE == "LSU":
                slot = "LSU0"
                if slots[slot].OP != "NOP":
                    raise ValueError("A bundle can contain at most 1 LSU instruction")
            else:
                raise ValueError(f"Unsupported instruction type: {instruction.TYPE}")
            slots[slot] = instruction

        if control_flow_count > 1:
            raise ValueError("A bundle can contain at most 1 control-flow instruction")

        return InstructionBundle(
            _Inst0=slots["ALU0"],
            _Inst1=slots["ALU1"],
            _Inst2=slots["SFU0"],
            _Inst3=slots["LSU0"],
        )

    @staticmethod
    def is_register(name):
        return name == "SP" or (
            name.startswith("R") and name[1:].isdigit() and 0 <= int(name[1:]) < 16
        )

    def register_index(self, name):
        if name == "SP":
            return 1
        if not self.is_register(name):
            raise ValueError(f"Invalid register: {name}")
        return int(name[1:])

    def read_register(self, name):
        return self.regs[self.register_index(name)]

    def write_register(self, name, value):
        index = self.register_index(name)
        if index != 0:
            self.regs[index] = value & 0xFFFFFFFF

    @staticmethod
    def parse_number(value):
        number = int(value, 0)
        if number & 0x100:
            number -= 0x200
        return number

    @staticmethod
    def parse_unsigned_number(value):
        return int(value, 0) & 0x1FF

    @staticmethod
    def arithmetic_shift_right(value, shift):
        value &= 0xFFFFFFFF
        if value & 0x80000000:
            value -= 1 << 32
        return value >> shift

    @staticmethod
    def signed32(value):
        value &= 0xFFFFFFFF
        return value - (1 << 32) if value & 0x80000000 else value

    @staticmethod
    def signed_divide(left, right):
        left = RedDSP.signed32(left)
        right = RedDSP.signed32(right)

        if right == 0:
            raise ZeroDivisionError("division by zero")

        quotient = abs(left) // abs(right)
        return -quotient if (left < 0) != (right < 0) else quotient

    def operand_value(self, name, instruction):
        if name in ("IMM", "OFFSET"):
            return self.parse_number(instruction.IMM)
        return self.read_register(getattr(instruction, name))

    def action_operand_value(self, name, instruction, action):
        if name == "IMM" and action in ("AND", "OR", "XOR"):
            return self.parse_unsigned_number(instruction.IMM)
        if name == "IMM" and action in ("SHL", "SHR"):
            return self.parse_unsigned_number(instruction.IMM) & 0x1F
        return self.operand_value(name, instruction)

    def branch_offset(self, instruction):
        offset = (int(instruction.DST, 0) << 9) | int(instruction.IMM, 0)
        if offset & (1 << 13):
            offset -= 1 << 14
        return offset

    def execute_action(self, instruction, definition):
        action = definition["ACTION"].split()
        action_name = action[0]

        if action_name == "NOP":
            return None
        # RET is an assembler alias for JMP, but a top-level function has no
        # caller. R15 is initialized to zero, so returning from such a
        # function terminates emulation instead of jumping back to bundle 0.
        if instruction.OP == "RET":
            return_address = self.read_register(instruction.DST)
            if return_address == 0:
                self.halted = True
                return None
            return return_address
        if action_name == "BEQ":
            taken = self.operand_value(action[1], instruction) == self.operand_value(
                action[2], instruction
            )
            return self.pc + self.branch_offset(instruction) * 16 if taken else None
        if action_name == "BNE":
            taken = self.operand_value(action[1], instruction) != self.operand_value(
                action[2], instruction
            )
            return self.pc + self.branch_offset(instruction) * 16 if taken else None
        if action_name == "JMP":
            return self.operand_value(action[1], instruction)
        if action_name == "CALL":
            self.write_register(instruction.DST, self.pc + 16)
            target = instruction.SRC1
            if self.is_register(target):
                return self.read_register(target)
            return int(target, 0)
        if action_name == "LOAD":
            address = self.operand_value(action[1], instruction) + self.operand_value(
                action[2], instruction
            )
            self.write_register(instruction.DST, self.memory.get(address, 0))
            return None
        if action_name == "STORE":
            address = self.operand_value(action[1], instruction) + self.operand_value(
                action[3], instruction
            )
            self.memory[address] = (
                self.operand_value(action[2], instruction) & 0xFFFFFFFF
            )
            return None

        if len(action) != 3:
            raise ValueError(f"Unsupported action: {' '.join(action)}")
        left = self.action_operand_value(action[1], instruction, action_name)
        right = self.action_operand_value(action[2], instruction, action_name)
        operations = {
            "ADD": lambda: left + right,
            "SUB": lambda: left - right,
            "MUL": lambda: left * right,
            "DIV": lambda: self.signed_divide(left, right),
            "MAC": lambda: self.read_register(instruction.DST) + left * right,
            "AND": lambda: left & right,
            "OR": lambda: left | right,
            "XOR": lambda: left ^ right,
            "SHL": lambda: left << right,
            "SHR": lambda: self.arithmetic_shift_right(left, right),
            "CMP": lambda: int(left == right),
            "CBE": lambda: int(self.signed32(left) >= self.signed32(right)),
        }
        operation = operations.get(action_name)
        if operation is None:
            raise ValueError(f"Unsupported action: {action_name}")
        if action_name == "DIV" and right == 0:
            raise ZeroDivisionError("division by zero")
        self.write_register(instruction.DST, operation())

    def execute_program(self, max_bundles=100000):
        """Execute bundles until termination or a control-flow error.

        ``max_bundles`` prevents malformed programs and intentional infinite
        loops from hanging the emulator forever. A normal top-level RET with
        R15 == 0 terminates execution.
        """
        self.pc = 0
        self.halted = False
        executed_bundles = 0
        while 0 <= self.pc < len(self.bundles) * 16:
            if executed_bundles >= max_bundles:
                raise ExecutionLimitExceeded(
                    f"execution exceeded {max_bundles} bundles at PC {self.pc}"
                )
            if self.pc % 16 != 0:
                raise ValueError(f"unaligned program counter: {self.pc}")
            bundle = self.bundles[self.pc // 16]
            next_pc = None
            for instruction in bundle.bundle.values():
                definition = self.isa_by_opcode[instruction.OP]
                result = self.execute_action(instruction, definition)
                if result is not None:
                    next_pc = result
            executed_bundles += 1
            if self.halted:
                break
            if self.regs[2] == EXIT_VALUE:
                self.halted = True
                break
            self.pc = self.pc + 16 if next_pc is None else next_pc


def main():
    parser = argparse.ArgumentParser(
        description="Execute a RED DSP VLIW assembly program."
    )
    parser.add_argument("assembly", help="Input RED DSP .s assembly file")
    parser.add_argument(
        "--isa",
        default="isa.csv",
        help="ISA CSV file (default: isa.csv)",
    )
    parser.add_argument(
        "--max-bundles",
        type=int,
        default=100000,
        help="Maximum number of bundles to execute (default: 100000)",
    )
    args = parser.parse_args()

    dsp = RedDSP()
    dsp.run(args.assembly, args.isa)
    dsp.execute_program(max_bundles=args.max_bundles)
    print(f"Final PC: {dsp.pc} (0x{dsp.pc:08X})")
    print(f"Registers: {dsp.regs}")
    print(f"Memory: {dict(sorted(dsp.memory.items()))}")


if __name__ == "__main__":
    main()
