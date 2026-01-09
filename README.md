<span class="badge-placeholder">[![GitHub release](https://img.shields.io/github/v/release/ekcbw/mypyc-aot)](https://github.com/ekcbw/mypyc-aot/releases/latest)</span>
<span class="badge-placeholder">[![License: MIT](https://img.shields.io/github/license/ekcbw/mypyc-aot)](https://github.com/ekcbw/mypyc-aot/blob/main/LICENSE)</span>

[English | [简体中文](README_zh.md)]

`mypyc_aot` is a performance optimization library based on [mypyc](https://github.com/mypyc/mypyc), supporting the acceleration of function/class performance using decorators, which is similar to the `numba` library but capable of accelerating general Python code. It enables leveraging modern performance from `mypyc` without the need to write `setup.py`, making it suitable for rapid prototyping, Jupyter notebooks, and similar scenarios.

## Installation

```bash
pip install mypyc_aot
```

After installation, ensure a C compiler (such as gcc, clang or msvc) is installed.

## Quick Start

### Basic Usage

Using mypyc_aot in Python scripts is straightforward:

```python
from mypyc_aot import Compiler

# Create a compiler instance
compiler = Compiler(globals())

# Use decorator to mark functions for optimization
@compiler.aot
def compute_sum(n: int) -> int:
    total = 0
    for i in range(n):
        total += i
    return total

# Start compilation
compiler.compile()

# Call the compiled function
result = compute_sum(10000000)
```

## Jupyter Integration

Using mypyc_aot in Jupyter notebooks:

1. Firstly load the extension:
```
%load_ext mypyc_aot
```

2. Use cell magic to mark functions for optimization:
```
%%mypyc_aot
def process_data(data: list[float]) -> float:
    result = 0.0
    for value in data:
        result += value * value
    return result
```

3. The function will be compiled and ready for subsequent calls.

## API Reference

### mypyc_aot_nocache() and mypyc_aot()

---

#### `mypyc_aot_nocache()` Function

Performs non-cached AOT compilation. Takes source code as input and returns the corresponding compiled module object.

```python
def mypyc_aot_nocache(
    pycode: str, 
    prefix: str = "mypyc_aot", 
    cache_dir: str | None = None, 
    quiet: bool = True, 
    compiler: str | None = None, 
    opt_level: str = "3", 
    strict_dunder_typing: bool = True, 
    experimental_features: bool = False
) -> module
```

##### Parameters
- **pycode** (str): Python source code string to be compiled
- **prefix** (str, optional): Prefix for generated module names, defaults to "mypyc_aot"
- **cache_dir** (str | None, optional): Cache directory path. If None, uses a temporary directory
- **quiet** (bool, optional): Silent mode. When True, suppresses compilation output, defaults to True
- **compiler** (str | None, optional): Specifies the C compiler name. If None, uses the default compiler
- **opt_level** (str, optional): Optimization level, defaults to "3" (maximum optimization)
- **strict_dunder_typing** (bool, optional): Whether to apply strict type checking to dunder methods, defaults to True
- **experimental_features** (bool, optional): Whether to enable experimental features, defaults to False

#### `mypyc_aot()` Function

Performs cached AOT compilation. If a cache exists, it is loaded directly; otherwise, compilation is performed and cached. Returns a compiled module object corresponding to the code.

```python
def mypyc_aot(
    pycode: str, 
    prefix: str = "mypyc_aot", 
    cache_dir: str = CACHE_DIR, 
    compression_method: str = DEFAULT_COMP_METHOD, 
    **kw
) -> module
```

##### Parameters
- **pycode** (str): Python source code string to be compiled
- **prefix** (str, optional): Prefix for generated module names, defaults to "mypyc_aot"
- **cache_dir** (str, optional): Cache directory path, defaults to `~/.mypyc_aot_cache`
- **compression_method** (str, optional): Cache compression method. Supports "zstandard", "zlib", or None (no compression). Defaults to DEFAULT_COMP_METHOD (automatically detects available compression libraries)
- **kw**: Additional keyword arguments passed to the `mypyc_aot_nocache()` function

### `Compiler` Class

`Compiler` is the core class of mypyc_aot, used to manage compilation environments and function optimization.

#### Initialization Parameters:
- `scope` (dict): Global namespace, typically `globals()`
- `ignored_vars` (list[str] | None): List of variable names to ignore
- `cache_dir` (str): Cache directory path, defaults to `.mypyc_aot_cache` in user home directory
- `quiet` (bool): Whether to use silent mode, controlling compilation output
- `compiler` (str | None): Specified C compiler
- `no_symbol_warnings` (bool): Whether to disable symbol warnings
- `ignore_import_not_found` (bool): Whether to ignore import not found errors
- `ignore_self` (bool): Whether to ignore the mypyc_aot module itself
- `**kw`: Other mypyc compilation options

#### Main Methods:

##### The `aot` Decorator
```python
@compiler.aot
def func(...):
    ...
```
Marks a function for AOT compilation optimization.  
Note that you cannot use `fn = compiler.aot(func)` instead of `@compiler.aot` since the compiler modifies `global()` scope when compilation is completed.

##### `add_func_or_class(source: str)`
Adds function or class source code string for compilation.

##### `add_source(source: str)`
Adds arbitrary source code string.

##### `compile()`
Executes the compilation process, writing compiled functions back to the scope.

##### `start_compilation_thread()`
Begins compilation in a background thread to avoid blocking the main thread.

##### `use_custom_compiler(cc: str, cxx: str)`
Specifies custom C/C++ compiler, for example:
```python
compiler.use_custom_compiler("gcc", "g++")
```

##### `get_source_code() -> str`
Retrieves all source code to be compiled.

## Notes

1. **Type Annotations**: For optimal optimization results, it is recommended to add type annotations for function parameters and return values.
2. **First-Run Delay**: Initial compilation requires time, but subsequent runs will use cache and be significantly faster.
3. **Compatibility**: Not all Python features support compilation optimization; complex dynamic features may not be optimizable.
4. **Cache Cleaning**: To force recompilation, delete the cache directory (default: `~/.mypyc_aot_cache`).

## Troubleshooting

There are a few directions to consider for troubleshooting:

1. Check if code complies with mypyc's type requirements.
2. Check the generated codes and intermediate files in the cache directory (e.g. `~/.mypyc_aot_cache/cache`).

## Version

Current `mypyc_aot` version: 1.0.2
