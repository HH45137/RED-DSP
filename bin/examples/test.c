

int test(int a, int b, int c) {
  if (a >= b) {
    if (b >= c)
      return b;
    if (a >= c)
      return c;
    return a;
  } else {
    if (a >= c)
      return a;
    if (b >= c)
      return c;
    return b;
  }
}

int main() {
  int result = test(2, 6, 7);
  return result;
}