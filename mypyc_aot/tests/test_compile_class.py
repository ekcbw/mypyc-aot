import sys, time
from mypy_extensions import i64
from mypyc_aot import Compiler

compiler = Compiler(globals())
if "--gcc" in sys.argv[1:]:
    compiler.use_custom_compiler("gcc", "g++")

@compiler.aot
class MyPyC:
    @staticmethod
    def compute(x: i64) -> i64:
        sum: i64 = 0
        for i in range(x):
            sum += i
        return sum

class PurePy:
    @staticmethod
    def compute(x: i64) -> i64:
        sum: i64 = 0
        for i in range(x):
            sum += i
        return sum

compiler.compile()

def main():
    n = 50000000

    start = time.perf_counter()
    result_normal = PurePy.compute(n)
    normal_time = time.perf_counter() - start

    start = time.perf_counter()
    result_mypyc = MyPyC.compute(n)
    mypyc_time = time.perf_counter() - start
    
    speedup = normal_time / mypyc_time
    print(f"Result: {result_mypyc}")
    print(f"mypyc: {mypyc_time:.3f}s")
    print(f"Pure Python: {normal_time:.3f}s")
    print(f"Speedup: {speedup:.2f}x")
    print(f"Results match: {result_mypyc == result_normal}")

if __name__ == "__main__":main()