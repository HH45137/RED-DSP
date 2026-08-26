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
    def __init__(self):
        self.bundles = []
        self.regs = [0] * 16
        self.memory = {}
        self.pc = 0
        self.isa_by_opcode = {}

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

    def parser(self, _AsmWords, _IsaDefine):
        self.bundles.clear()
        isa_by_opcode = {item["OP"]: item for item in _IsaDefine}

        for source_line in _AsmWords:
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
            if len(fields) != 4:
                raise ValueError(f"{opcode} expects 4 operands")
            for actual, requirement in zip(fields, expected):
                if requirement == "GR" and not self.is_register(actual):
                    raise ValueError(f"{opcode}: expected register, got {actual}")

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

    def operand_value(self, name, instruction):
        if name == "IMM":
            return self.parse_number(instruction.IMM)
        return self.read_register(getattr(instruction, name))

    def execute_action(self, instruction, definition):
        action = definition["ACTION"].split()
        operation = action[0]
        if operation == "NOP":
            return None
        if operation in ("BEQ", "BNE"):
            equal = self.operand_value(action[1], instruction) == self.operand_value(
                action[2], instruction
            )
            if (operation == "BEQ" and equal) or (operation == "BNE" and not equal):
                offset = (int(instruction.DST, 0) << 9) | int(instruction.IMM, 0)
                if offset & (1 << 13):
                    offset -= 1 << 14
                return self.pc + offset * 16
            return self.pc + 16
        if operation == "JMP":
            return self.read_register(instruction.DST)
        if operation == "CALL":
            target = self.read_register(instruction.SRC1)
            self.write_register(instruction.DST, self.pc + 16)
            return target
        if operation == "LOAD":
            address = self.operand_value(action[1], instruction) + self.parse_number(
                instruction.IMM
            )
            self.write_register(instruction.DST, self.memory.get(address, 0))
            return None
        if operation == "STORE":
            address = self.read_register(instruction.DST) + self.parse_number(
                instruction.IMM
            )
            self.memory[address] = self.read_register(instruction.SRC1) & 0xFFFFFFFF
            return None
        left = self.operand_value(action[1], instruction)
        right = self.operand_value(action[2], instruction)
        if operation == "MAC":
            result = self.read_register(instruction.DST) + left * right
            self.write_register(instruction.DST, result)
            return None
        if operation == "DIV" and right == 0:
            raise ZeroDivisionError("division by zero")
        operations = {
            "ADD": left + right,
            "SUB": left - right,
            "MUL": left * right,
            "DIV": left // right,
            "AND": left & right,
            "OR": left | right,
            "XOR": left ^ right,
            "SHL": left << right,
            "SHR": left >> right,
            "CMP": int(left == right),
        }
        if operation not in operations:
            raise ValueError(f"Unsupported action: {operation}")
        result = operations[operation]
        self.write_register(instruction.DST, result)

    def execute_program(self):
        self.pc = 0
        while 0 <= self.pc < len(self.bundles) * 16:
            instruction = self.bundles[self.pc // 16].bundle["ALU0"]
            definition = self.isa_by_opcode[instruction.OP]
            next_pc = self.execute_action(instruction, definition)
            self.pc = self.pc + 16 if next_pc is None else next_pc


if __name__ == "__main__":
    dsp = RedDSP()

    dsp.run("emu/asm/helloworld.s", "emu/isa.csv")
    dsp.execute_program()
    print(dsp.regs)
