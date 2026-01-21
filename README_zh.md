[[English](README.md) | 简体中文]

`mypyc_aot`是基于[mypyc](https://github.com/mypyc/mypyc)的性能优化库，支持用装饰器加速函数/类的性能，类似`numba`库但支持加速通用Python代码，
使得利用`mypyc`的现代性能不再需要编写`setup.py`，适用于快速原型，以及jupyter等场景。

## 安装

```bash
pip install mypyc_aot
```

安装完成后，确保已安装 C 编译器（如 gcc、clang 或 msvc）。

## 快速开始

### 基本用法

在 Python 脚本中使用 mypyc_aot：

```python
from mypyc_aot import Compiler

# 创建编译器实例
compiler = Compiler(globals())

# 使用装饰器标记需优化的函数
@compiler.aot
def compute_sum(n: int) -> int:
    total = 0
    for i in range(n):
        total += i
    return total

# 开始编译
compiler.compile()

# 调用编译后的函数
result = compute_sum(10000000)
```

## Jupyter 集成

在 Jupyter 笔记本中使用 mypyc_aot：

1. 首先加载扩展：
```
%load_ext mypyc_aot
```

2. 用单元格魔法标记需要优化的函数：
```
%%mypyc_aot
def process_data(data: list[float]) -> float:
    result = 0.0
    for value in data:
        result += value * value
    return result
```

3. 函数将编译并可用于后续调用

## API 参考

### mypyc_aot_nocache() 和 mypyc_aot()

---

#### `mypyc_aot_nocache()` 函数

执行无缓存的 AOT 编译。接受源代码作为输入，返回相应的已编译模块对象。

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

##### 参数
- **pycode** (str): 要编译的 Python 源代码字符串
- **prefix** (str, 可选): 生成模块名的前缀，默认为 "mypyc_aot"
- **cache_dir** (str | None, 可选): 缓存目录路径。如果为 None，则使用临时目录
- **quiet** (bool, 可选): 静默模式。当为 True 时，抑制编译输出，默认为 True
- **compiler** (str | None, 可选): 指定 C 编译器名称。如果为 None，则使用默认编译器
- **opt_level** (str, 可选): 优化级别，默认为 "3"（最大优化）
- **strict_dunder_typing** (bool, 可选): 是否对双下划线方法应用严格的类型检查，默认为 True
- **experimental_features** (bool, 可选): 是否启用实验性功能，默认为 False

#### `mypyc_aot()` 函数

执行带缓存的 AOT 编译。如果缓存存在，则直接加载；否则执行编译并缓存。返回与代码对应的已编译模块对象。

```python
def mypyc_aot(
    pycode: str, 
    prefix: str = "mypyc_aot", 
    cache_dir: str = CACHE_DIR, 
    compression_method: str = DEFAULT_COMP_METHOD, 
    **kw
) -> module
```

##### 参数
- **pycode** (str): 要编译的 Python 源代码字符串
- **prefix** (str, 可选): 生成模块名的前缀，默认为 "mypyc_aot"
- **cache_dir** (str, 可选): 缓存目录路径，默认为 `~/.mypyc_aot_cache`
- **compression_method** (str, 可选): 缓存压缩方法。支持 "zstandard"、"zlib" 或 None（不压缩）。默认为 DEFAULT_COMP_METHOD（自动检测可用的压缩库）
- **kw**: 传递给 `mypyc_aot_nocache()` 函数的额外关键字参数

### `Compiler` 类

`Compiler` 是 mypyc_aot 的核心类，用于管理编译环境和函数优化。

#### 初始化参数：
- `scope` (dict): 全局命名空间，通常为 `globals()`
- `ignored_vars` (list[str] | None): 需要忽略的变量名列表
- `cache_dir` (str): 缓存目录路径，默认为用户主目录下的 `.mypyc_aot_cache`
- `quiet` (bool): 是否静默模式，控制编译输出
- `compiler` (str | None): 指定 C 编译器
- `no_symbol_warnings` (bool): 是否禁止符号警告
- `ignore_import_not_found` (bool): 是否忽略导入未找到错误
- `ignore_self` (bool): 是否忽略 mypyc_aot 模块自身
- `**kw`: 其他 mypyc 编译选项

#### 主要方法：

##### `aot` 装饰器
```python
@compiler.aot
def func(...):
    ...
```
标记函数进行 AOT 编译优化。  
注意：不能使用 `fn = compiler.aot(func)` 代替 `@compiler.aot`，因为编译器在编译完成时会修改 `global()` 作用域。

##### `add_func_or_class(source: str)`
添加函数或类的源代码字符串进行编译。

##### `add_source(source: str)`
添加任意源代码字符串。

##### `compile()`
执行编译过程，将编译后的函数写回作用域。

##### `start_compilation_thread()`
在后台线程中开始编译，避免阻塞主线程。

##### `use_custom_compiler(cc: str, cxx: str)`
指定自定义的 C/C++ 编译器，例如：
```python
compiler.use_custom_compiler("gcc", "g++")
```

##### `get_source_code() -> str`
获取所有待编译的源代码。

## 注意事项

1. **类型注解**：为了获得最佳优化效果，建议为函数参数和返回值添加类型注解。
2. **首次运行延迟**：首次编译需要时间，后续运行将使用缓存，速度显著提升。
3. **兼容性**：并非所有 Python 特性都支持编译优化，复杂动态特性可能无法优化。
4. **缓存清理**：如果需要强制重新编译，可以删除缓存目录（默认为 `~/.mypyc_aot_cache`）。

## 故障排除

可以考虑以下几种故障排除方向：

1. 检查代码是否符合 mypyc 的类型要求。
2. 检查缓存目录中生成的代码和中间文件（例如 `~/.mypyc_aot_cache/cache`）。

## 版本

当前`mypyc_aot`版本：1.0.3
