import math
import time
from mypy_extensions import i64
from librt.vecs import vec
from mypyc_aot import Compiler

MODULO: i64 = 1000000007

compiler = Compiler(globals(), experimental_features=True)

@compiler.aot
def fib(n: i64) -> i64:
    if 0 <= n <= 1:
        return n

    modulo = MODULO
    a: i64 = 0
    b: i64 = 1
    for _ in range(2, n + 1):
        a, b = b, (a + b) % modulo
    return b

def fib_cpy(n: i64) -> i64:
    if 0 <= n <= 1:
        return n

    modulo = MODULO
    a: i64 = 0
    b: i64 = 1
    for _ in range(2, n + 1):
        a, b = b, (a + b) % modulo
    return b

@compiler.aot
def simulate_vec(bodies: vec[vec[float]], g: float, t: float, dt: float) -> None:
    """
    Simulate N-body physics using Symplectic Euler method.
    
    Layout of each body:
    [0]: mass, [1]: x, [2]: y, [3]: vx, [4]: vy
    """
    steps = int(t / dt)
    n = len(bodies)
    
    for _ in range(steps):
        # Step 1: Compute forces and update velocities simultaneously
        for i in range(n):
            b_i = bodies[i]
            m_i = b_i[0]
            x_i = b_i[1]
            y_i = b_i[2]
            
            for j in range(i + 1, n):
                b_j = bodies[j]
                m_j = b_j[0]
                dx = b_j[1] - x_i
                dy = b_j[2] - y_i
                
                # Softening factor to prevent division by zero
                dist_sq = dx * dx + dy * dy + 1e-9
                dist = math.sqrt(dist_sq)
                
                # Common force factor: G / (r^3) * dt
                common_factor = (g / (dist_sq * dist)) * dt
                
                # dv_i = G * m_j * dt * dir / r^2
                b_i[3] += common_factor * m_j * dx
                b_i[4] += common_factor * m_j * dy
                
                # dv_j = G * m_i * dt * (-dir) / r^2
                b_j[3] -= common_factor * m_i * dx
                b_j[4] -= common_factor * m_i * dy
        
        # Step 2: Update positions using the newly calculated velocities
        for i in range(n):
            b_i = bodies[i]
            b_i[1] += b_i[3] * dt
            b_i[2] += b_i[4] * dt

def simulate_list(bodies: list[list[float]], g: float, t: float, dt: float) -> None:
    """
    Simulate N-body physics using Symplectic Euler method.
    
    Layout of each body:
    [0]: mass, [1]: x, [2]: y, [3]: vx, [4]: vy
    """
    steps = int(t / dt)
    n = len(bodies)
    
    for _ in range(steps):
        # Step 1: Compute forces and update velocities simultaneously
        for i in range(n):
            b_i = bodies[i]
            m_i = b_i[0]
            x_i = b_i[1]
            y_i = b_i[2]
            
            for j in range(i + 1, n):
                b_j = bodies[j]
                m_j = b_j[0]
                dx = b_j[1] - x_i
                dy = b_j[2] - y_i
                
                # Softening factor to prevent division by zero
                dist_sq = dx * dx + dy * dy + 1e-9
                dist = math.sqrt(dist_sq)
                
                # Common force factor: G / (r^3) * dt
                common_factor = (g / (dist_sq * dist)) * dt
                
                # dv_i = G * m_j * dt * dir / r^2
                b_i[3] += common_factor * m_j * dx
                b_i[4] += common_factor * m_j * dy
                
                # dv_j = G * m_i * dt * (-dir) / r^2
                b_j[3] -= common_factor * m_i * dx
                b_j[4] -= common_factor * m_i * dy
        
        # Step 2: Update positions using the newly calculated velocities
        for i in range(n):
            b_i = bodies[i]
            b_i[1] += b_i[3] * dt
            b_i[2] += b_i[4] * dt

simulate_list_cpy = simulate_list
simulate_list = compiler.aot(simulate_list) # type: ignore
compiler.compile()

def run_fib_benchmark():
    n = 10000000

    print(f"\nStarting fibonacci benchmark...")
    start_time = time.perf_counter()
    result = fib(n)
    mypyc_execution_time = time.perf_counter() - start_time

    start_time = time.perf_counter()
    result = fib_cpy(n)
    cpython_execution_time = time.perf_counter() - start_time

    print(f"Fibonacci({n}) mod {MODULO} = {result}")
    print(f"Mypyc: {mypyc_execution_time:.4f} seconds")
    print(f"CPython: {cpython_execution_time:.4f} seconds")

def run_nbody_benchmark():
    g_constant = 1.0
    total_time = 100.0
    time_step = 0.0001
    radius = 1.0
    bodies_data = [
        [10.0, 0.0, 0.0, 0.0, 0.0],
        [0.001, radius, 0.0, 0.0, 0.0],
    ]
    bodies_data[1][4] = math.sqrt(g_constant * bodies_data[0][0] / radius) # 圆轨道

    print(f"\nStarting N-body simulation benchmark...")

    # 1. 运行 mypyc 编译的 vec 版本
    bodies = vec[vec[float]]([vec[float](item) for item in bodies_data])
    start_time = time.perf_counter()
    simulate_vec(bodies, g_constant, total_time, time_step)
    mypyc_execution_time = time.perf_counter() - start_time

    # 2. 运行 mypyc 编译的 list 版本
    start_time = time.perf_counter()
    simulate_list(bodies_data, g_constant, total_time, time_step)
    mypyc_list_exec_time = time.perf_counter() - start_time

    # 3. 运行 CPython list 版本
    start_time = time.perf_counter()
    simulate_list_cpy(bodies_data, g_constant, total_time, time_step)
    cpython_execution_time = time.perf_counter() - start_time

    orbital_radius = math.sqrt((bodies[0][1]-bodies[1][1])**2 + \
                               (bodies[0][2]-bodies[1][2])**2)

    print(f"Final orbital radius: {orbital_radius:.8f}")
    print(f"Mypyc with vec: {mypyc_execution_time:.4f} seconds")
    print(f"Mypyc with list: {mypyc_list_exec_time:.4f} seconds")
    print(f"CPython: {cpython_execution_time:.4f} seconds")

if __name__ == "__main__":
    run_fib_benchmark()
    run_nbody_benchmark()