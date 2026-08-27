# RED DSP

## ISA

### General

- VLIW
- Little-Endian

### VLIW Bundle Format

The total size of the package = PKG_SIZE = 4 * 32-bits = 128-bits = 16-Bytes

|             | ALU0              | ALU1              | SFU0                             | LSU0                     |
| ----------- | ----------------- | ----------------- | -------------------------------- | ------------------------ |
| Description | ALU instruction 0 | ALU instruction 1 | Special mathematical instruction | Load & Store instruction |
| Size (bits) | 32                | 32                | 32                               | 32                       |

### Register

Each register is 32-bits in size, and there are a total of 16 registers.
The 5-bit register fields must use R0-R15. R16-R31 are reserved.

| Name      | Description                                                                               |
| --------- | ----------------------------------------------------------------------------------------- |
| R0        | Always zero                                                                               |
| R1/SP     | Stack Pointer                                                                             |
| R2-R15/GR | General Register                                                                          |
| PC        | Program Counter (Must be aligned at intervals of PKG_SIZE and hidden from the programmer) |

- Writing R0 has no effect. Reading R0 returns zero.

### Instruction Format

Each instruction is 32-bits in size.

| Type | Size (bit) | Description               |
| ---- | ---------- | ------------------------- |
| OP   | 8          | Opcode                    |
| DST  | 5          | Target register address   |
| SRC1 | 5          | Source 1 register address |
| SRC2 | 5          | Source 2 register address |
| IMM  | 9          | Immediate value           |

- `IMM` is a signed 9-bit value for arithmetic, compare, load, and store instructions.
- `IMM` is zero-extended for logical instructions.
- The shift count is `SRC2[4:0]` or `IMM[4:0]`.
- `SFR` is an arithmetic right shift.
- `CMP` writes `0` for false and `1` for true.

### Instructions

The instruction table is defined in [`../emu/isa.csv`](../emu/isa.csv).
This CSV file is the single source of truth for instruction fields and descriptions.

- `ALU` instructions use ALU0 or ALU1.
- `SFU` instructions use SFU0.
- `LSU` instructions use LSU0.
- `FAKE` instructions are assembler aliases.

#### Load & Store

- `OFFSET = sign_extend(IMM[8:0])`.
- `LD` and `ST` access one 32-bit word.
- For `ST`, the `DST` field is the address base. It is not written.
- Address alignment is 4 bytes.

#### Flow Control

The branch offset is a signed 14-bit value:

- `OFFSET[13:0] = { DST[4:0], IMM[8:0] }`
- `PC = PC + sign_extend(OFFSET) * PKG_SIZE` when the branch is taken.
- `JMP` uses the `DST` field as the target register. The field is not written.
- `CALL` writes the return address to `DST` and uses `SRC1` as the target register.
- Jump targets must be aligned to `PKG_SIZE`.

### Execution Rules

- Each bundle has ALU0, ALU1, SFU0, and LSU0 slots.
- The current emulator executes the ALU0 instruction only.
- Integer results wrap to 32 bits.
- Division by zero raises an error.
