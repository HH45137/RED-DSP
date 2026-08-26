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

| Name      | Description                                                                               |
| --------- | ----------------------------------------------------------------------------------------- |
| R0        | Always zero                                                                               |
| R1/SP     | Stack Pointer                                                                             |
| R2-R15/GR | General Register                                                                          |
| PC        | Program Counter (Must be aligned at intervals of PKG_SIZE and hidden from the programmer) |

### Instruction Format

Each instruction is 32-bits in size.

| Type | Size (bit) | Description               |
| ---- | ---------- | ------------------------- |
| OP   | 8          | Opcode                    |
| DST  | 5          | Target register address   |
| SRC1 | 5          | Source 1 register address |
| SRC2 | 5          | Source 2 register address |
| IMM  | 9          | Immediate value           |

### Instructions

- The \#* is get address
- The [*] is get data

#### Basic mathematical calculations (ALU)

| ID  | OP          | DST | SRC1 | SRC2 | IMM   | Description       |
| --- | ----------- | --- | ---- | ---- | ----- | ----------------- |
| 1   | ADD.INT     | GR  | GR   | GR   | X     | DST = SRC1 + SRC2 |
| 2   | SUB.INT     | GR  | GR   | GR   | X     | DST = SRC1 - SRC2 |
| 3   | MUL.INT     | GR  | GR   | GR   | X     | DST = SRC1 * SRC2 |
| 4   | DIV.INT     | GR  | GR   | GR   | X     | DST = SRC1 / SRC2 |
| 5   | ADD.INT.IMM | GR  | GR   | X    | VALUE | DST = SRC1 + IMM  |
| 6   | SUB.INT.IMM | GR  | GR   | X    | VALUE | DST = SRC1 - IMM  |
| 7   | MUL.INT.IMM | GR  | GR   | X    | VALUE | DST = SRC1 * IMM  |
| 8   | DIV.INT.IMM | GR  | GR   | X    | VALUE | DST = SRC1 / IMM  |

#### Special mathematical calculations (SFU)

| ID  | OP          | DST | SRC1 | SRC2 | IMM   | Description        |
| --- | ----------- | --- | ---- | ---- | ----- | ------------------ |
| 1   | MAC.INT     | GR  | GR   | GR   | X     | DST += SRC1 * SRC2 |
| 2   | MAC.INT.IMM | GR  | GR   | X    | VALUE | DST += SRC1 * IMM  |

#### Logical calculations (ALU)

| ID  | OP      | DST | SRC1 | SRC2 | IMM   | Description        |
| --- | ------- | --- | ---- | ---- | ----- | ------------------ |
| 1   | AND     | GR  | GR   | GR   | X     | DST = SRC1 & SRC2  |
| 2   | OR      | GR  | GR   | GR   | X     | DST = SRC1 \| SRC2 |
| 3   | XOR     | GR  | GR   | GR   | X     | DST = SRC1 ^ SRC2  |
| 4   | SFL     | GR  | GR   | GR   | X     | DST = SRC1 << SRC2 |
| 5   | SFR     | GR  | GR   | GR   | X     | DST = SRC1 >> SRC2 |
| 6   | CMP     | GR  | GR   | GR   | X     | DST = SRC1 == SRC2 |
| 7   | AND.IMM | GR  | GR   | X    | VALUE | DST = SRC1 & IMM   |
| 8   | OR.IMM  | GR  | GR   | X    | VALUE | DST = SRC1 \| IMM  |
| 9   | XOR.IMM | GR  | GR   | X    | VALUE | DST = SRC1 ^ IMM   |
| 10  | SFL.IMM | GR  | GR   | X    | VALUE | DST = SRC1 << IMM  |
| 11  | SFR.IMM | GR  | GR   | X    | VALUE | DST = SRC1 >> IMM  |
| 12  | CMP.IMM | GR  | GR   | X    | VALUE | DST = SRC1 == IMM  |

#### Load & Store (LSU)
- The OFFSET = sign_extend({ IMM })

| ID  | OP  | DST | SRC1 | SRC2 | IMM    | Description           |
| --- | --- | --- | ---- | ---- | ------ | --------------------- |
| 1   | LD  | GR  | GR   | X    | OFFSET | DST = [SRC1 + OFFSET] |
| 2   | ST  | GR  | GR   | X    | OFFSET | [DST + OFFSET] = SRC1 |

#### Flow control (ALU)

The offset for branch instructions is formed by concatenating the 5-bit DST field (as the upper bits) with the 9-bit IMM field (as the lower bits), then sign-extended to 32 bits:

- OFFSET = sign_extend( { DST[4:0], IMM[8:0] } )
- The final branch target is: PC += OFFSET * PKG_SIZE

| ID  | OP   | DST                         | SRC1 | SRC2 | IMM         | Description                                                  |
| --- | ---- | --------------------------- | ---- | ---- | ----------- | ------------------------------------------------------------ |
| 1   | BEQ  | OFFSET[13:9]                | GR   | GR   | OFFSET[8:0] | if (SRC1 == SRC2) PC += sign_extend(OFFSET) * PKG_SIZE       |
| 2   | BNE  | OFFSET[13:9]                | GR   | GR   | OFFSET[8:0] | if (SRC1 != SRC2) PC += sign_extend(OFFSET) * PKG_SIZE       |
| 3   | JMP  | GR (must align to PKG_SIZE) | X    | X    | X           | PC = DST                                                     |
| 4   | CALL | GR                          | GR   | X    | X           | DST = PC + PKG_SIZE; PC = SRC1 (SRC1 must align to PKG_SIZE) |
