int test(int a, int b, int c);

int main() { return test(12, 18, 24); }

int test(int a, int b, int c) {
  if (a == 0 || b == 0 || c == 0) {
    return 0;
  }

  int x = a;
  int y = b;
  int r;
  while (y != 0) {
    r = x % y;
    x = y;
    y = r;
  }
  int gcd_ab = x;
  int lcm_ab = a / gcd_ab * b;

  x = lcm_ab;
  y = c;
  while (y != 0) {
    r = x % y;
    x = y;
    y = r;
  }
  int gcd_abc = x;
  int lcm_abc = lcm_ab / gcd_abc * c;

  return lcm_abc;
}
