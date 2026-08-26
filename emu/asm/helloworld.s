// Hello World

// R2 = R0 + 0x5; (R2 == 5)
ADD.INT.IMM R2 R0 X 0x5
// R3 = R2 - 0x3; (R3 == 2)
SUB.INT.IMM R3 R2 X 0x3
// R4 = R3 * 0x72; (R4 == 228)
MUL.INT.IMM R4 R3 X 0x72
// R5 = R4 / 0x9； (R5 == 25)
DIV.INT.IMM R5 R4 X 0x9
