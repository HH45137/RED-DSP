int test(int a, int b, int c);

int main() { return test(12, 18, 24); }

int test(int a, int b, int c) {
  // Local array -> force the LSU to use LD (load) and ST (store)
  int arr[4];
  arr[0] = a;
  arr[1] = b;
  arr[2] = c;

  // ---- 1. Cover all ALU arithmetic (immediate and register variants) ----
  int t1 = a + 5; // ADD.IMM
  t1 = t1 - 3;    // SUB.IMM
  t1 = t1 * 2;    // MUL.IMM
  t1 = t1 / 4;    // DIV.IMM

  int t2 = b - c;  // SUB.INT
  int t3 = a * b;  // MUL.INT
  int t4 = t3 / c; // DIV.INT (c=24/22, safe)

  // ---- 2. Cover all ALU logic (AND/OR/XOR, including immediate) ----
  int xor_reg = a ^ b;          // XOR.INT
  int bits = (a & b) | xor_reg; // AND.INT, OR.INT
  bits = bits ^ 0xFF;           // XOR.IMM
  bits = bits & 0x0F;           // AND.IMM
  bits = bits | 0x80;           // OR.IMM

  // ---- 3. Cover all ALU shifts (immediate and register variants) ----
  int sh_imm = (a << 2) | (b >> 1); // SFL.IMM, SFR.IMM
  int sh_reg = (a << c) | (b >> a); // SFL.INT, SFR.INT (a,c both <32, safe)

  // ---- 4. Cover the SFU multiply-add (MAC.INT and MAC.IMM) ----
  int mac = 0;
  mac = mac + t2 * t3; // MAC.INT (equivalent to DST += SRC1*SRC2)
  mac = mac + c * 3;   // MAC.IMM (equivalent to DST += SRC1*IMM)

  // ---- 5. Core reduction computation (loop: forces JMP + BNE) ----
  int result = mac + t1 + t4 + sh_imm + sh_reg + bits;
  int i = 0;
  while (i < 3) {        // Loop control -> JMP (backward) + BNE (conditional)
    if (i == 0) {        // CMP.IMM + BEQ (branch on equal)
      result += arr[i];  // LD (load from arr)
    } else if (i >= 1) { // CBE (i.e. SRC1 >= SRC2)
      result -= arr[i];  // LD
    } else {
      result ^= arr[i]; // LD
    }
    i++;
  }

  // ---- 6. Memory store (ST) ----
  arr[3] = result;

  // ---- 7. Recursive call (forces CALL and RET) with more branches (CBE/BNE) ----
  if (a > 10) {                       // CBE or CMP + BNE
    return test(a - 3, b + 1, c - 2); // CALL (recursive) + RET (on return)
  }

  // ---- 8. Load from memory again (LD) and final branch (forces BEQ / BNE) ----
  int final = arr[0] + arr[1] + arr[2] + arr[3]; // Multiple LD operations

  if (final == 0) { // BEQ
    return 0;
  }
  if (final != 100) { // BNE
    return final;
  }
  return 100; // RET
}