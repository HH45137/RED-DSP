int test(int a, int b, int c);

int main() { return test(12, 18, 24); }

int test(int a, int b, int c) {
  // 局部数组 → 强制使用 LSU 的 LD（加载）和 ST（存储）
  int arr[4];
  arr[0] = a;
  arr[1] = b;
  arr[2] = c;

  // ---- 1. 覆盖所有 ALU 算术（立即数与寄存器版本） ----
  int t1 = a + 5; // ADD.IMM
  t1 = t1 - 3;    // SUB.IMM
  t1 = t1 * 2;    // MUL.IMM
  t1 = t1 / 4;    // DIV.IMM

  int t2 = b - c;  // SUB.INT
  int t3 = a * b;  // MUL.INT
  int t4 = t3 / c; // DIV.INT (c=24/22，安全)

  // ---- 2. 覆盖所有 ALU 逻辑（AND/OR/XOR，含立即数） ----
  int xor_reg = a ^ b;          // XOR.INT
  int bits = (a & b) | xor_reg; // AND.INT, OR.INT
  bits = bits ^ 0xFF;           // XOR.IMM
  bits = bits & 0x0F;           // AND.IMM
  bits = bits | 0x80;           // OR.IMM

  // ---- 3. 覆盖所有 ALU 移位（立即数与寄存器版本） ----
  int sh_imm = (a << 2) | (b >> 1); // SFL.IMM, SFR.IMM
  int sh_reg = (a << c) | (b >> a); // SFL.INT, SFR.INT (a,c 均<32安全)

  // ---- 4. 覆盖 SFU 乘加（MAC.INT 和 MAC.IMM） ----
  int mac = 0;
  mac = mac + t2 * t3; // MAC.INT (等价于 DST += SRC1*SRC2)
  mac = mac + c * 3;   // MAC.IMM (等价于 DST += SRC1*IMM)

  // ---- 5. 核心归约计算（含循环：强制 JMP + BNE） ----
  int result = mac + t1 + t4 + sh_imm + sh_reg + bits;
  int i = 0;
  while (i < 3) {        // 循环控制 → JMP（跳回） + BNE（条件跳）
    if (i == 0) {        // CMP.IMM + BEQ（相等跳）
      result += arr[i];  // LD（从 arr 加载）
    } else if (i >= 1) { // CBE（即 SRC1 >= SRC2）
      result -= arr[i];  // LD
    } else {
      result ^= arr[i]; // LD
    }
    i++;
  }

  // ---- 6. 内存存储（ST） ----
  arr[3] = result;

  // ---- 7. 递归调用（强制 CALL 和 RET），同时包含更多分支（CBE/BNE） ----
  if (a > 10) {                       // CBE 或 CMP + BNE
    return test(a - 3, b + 1, c - 2); // CALL（递归） + RET（返回时）
  }

  // ---- 8. 再次从内存加载（LD）并做最终分支（强制 BEQ / BNE） ----
  int final = arr[0] + arr[1] + arr[2] + arr[3]; // 多次 LD 操作

  if (final == 0) { // BEQ
    return 0;
  }
  if (final != 100) { // BNE
    return final;
  }
  return 100; // RET
}