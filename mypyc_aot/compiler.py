import re, ast, inspect, warnings, functools, itertools, threading
from typing import Any, _Final
from .mypyc_aot import mypyc_aot_nocache, mypyc_aot, CACHE_DIR
from .unix_compiler_util import init_custom_unix_compiler, restore_default_compiler

__all__ = ["Compiler"]

AOT_PATTERN = re.compile(r"^@([0-9A-Za-z_]+?)\.aot[^\n]*?\n")
IGNORED_NAMES = ["__annotations__", "__builtins__", "__cached__",
                 "__loader__", "__spec__"]
BASIC_TYPES = {int, float, str, bytes, bytearray, list,
               tuple, dict, set, type(None), type(range(0)), slice}
REPR_TYPES = {re.Pattern}

def is_representable(obj): # 检查对象能否被repr()表示
    # obj为非闭包类
    if isinstance(obj, (type, _Final)) and \
        obj.__name__ == obj.__qualname__: # type: ignore[union-attr]
        return True
    elif type(obj) in BASIC_TYPES: # 不使用isinstance（由于不能是基本类型子类）
        if type(obj) in (list, tuple, dict, set, frozenset):
            if isinstance(obj, dict):
                obj = itertools.chain(obj.keys(), obj.values())
            return all(is_representable(sub) for sub in obj)
        return True
    elif type(obj) in REPR_TYPES:
        return True
    return False

class ReprWrapper:
    def __init__(self, obj, repr_func):
        self.obj = obj
        self.repr_func = repr_func
    def __repr__(self) -> str:
        return self.repr_func(self.obj)

def get_source(function_or_type) -> str | None:
    try:
        source = inspect.getsource(function_or_type)
    except OSError:
        return None
    if source.startswith(" "):
        raise ValueError(f"""Cannot compile methods or closure functions \
({function_or_type.__qualname__}). Use @aot for outermost codes.""") # type: ignore[return]
    source = re.sub(AOT_PATTERN, "", source) # 去除compiler.aot
    return source

def parse_name_from_source(source: str) -> str:
    parsed = ast.parse(source)
    if len(parsed.body) != 1 or not \
        isinstance(parsed.body[0], (ast.FunctionDef, ast.ClassDef)):
        raise ValueError("not a function or class")
    return parsed.body[0].name

class Compiler:
    _scope: dict
    _added_symbols: set[str]
    _cache_dir: str | None
    _quiet: bool
    _compiler: str | None
    _ignore_import_not_found: bool
    _ignore_self: bool
    _custom_compiler: dict[str, str] | None
    _codes: list[str]
    _comp_thread: threading.Thread | None
    _modules: set[str] # add_symbols_from中临时使用
    _exported_names: set[str]
    _orig_module_names: dict[str, str] # 函数/类编译前的模块名（__module__）
    _has_class_in_source: bool
    def __init__(self, scope: dict, ignored_vars: list[str] | None = None,
                 cache_dir=CACHE_DIR, quiet=True, compiler=None,
                 no_symbol_warnings=False, ignore_import_not_found=True,
                 ignore_self=True, **kw):
        self._scope = scope
        self._cache_dir = cache_dir
        self._quiet = quiet
        self._compiler = compiler
        self._ignore_import_not_found = ignore_import_not_found
        self._ignore_self = ignore_self
        self._kw_options = kw
        self._custom_compiler = None
        self._codes = []
        self._comp_thread = None
        self._added_symbols = set()
        self._modules = set()
        self._exported_names = set()
        self._orig_module_names = {}
        self._has_class_in_source = False
        self.add_symbols_from(self._scope, ignored_vars, no_symbol_warnings)
    def add_symbols_from(self, scope: dict, ignored_vars: list[str] | None = None,
                         no_warnings=False):
        if ignored_vars is None: ignored_vars = []
        annotations: dict[str, Any] = self._scope.get("__annotations__",{})

        for name, value in list(scope.items()): # scope可能会改变大小
            if name in IGNORED_NAMES or name in ignored_vars:
                continue
            self._added_symbols.add(name)
            if name in ["__doc__", "__package__"] and value is None:
                continue # 避免Incompatible types in assignment

            if inspect.ismodule(value):
                # 忽略mypyc_aot模块自身
                if self._ignore_self and value.__name__.startswith("mypyc_aot"):
                    continue
                if value.__name__ == name:
                    self._modules.add(name)
                else:
                    self._codes.append(f"import {value.__name__} as {name}")
            elif isinstance(value, type) or inspect.isfunction(value) \
                or inspect.isbuiltin(value):
                if self._ignore_self and value.__module__.startswith("mypyc_aot"):
                    continue
                if value.__module__ == __name__:
                    source = get_source(value)
                    if source is not None:
                        self._codes.append(source)
                        continue
                self._orig_module_names[name] = value.__module__
                comment = " # type: ignore[import-not-found]" \
                          if self._ignore_import_not_found else ""
                self._codes.append(
                    f"from {value.__module__} import {value.__name__} as {name}{comment}")
            elif is_representable(value):
                type_ = None
                if name in annotations:
                    type_ = self._repr(annotations[name])
                elif isinstance(value, _Final): # typing模块中的类型
                    self._modules.add("typing")
                    type_ = "typing.Any"

                if type_ is not None:
                    self._codes.append(f"{name}: {type_} = {self._repr(value)}")
                else:
                    self._codes.append(f"{name} = {self._repr(value)}")
            elif not no_warnings:
                warnings.warn(f"skipping variable {name} ({repr(value)[:100]})")

        self._codes = [f"import {mod}" for mod in sorted(self._modules)] + self._codes
        self._modules.clear()
    def _repr(self, obj) -> str:
        if obj is type(None):
            return "type(None)"
        if isinstance(obj, (type, _Final)):
            self._modules.add(obj.__module__) # type: ignore[union-attr]
            return f"{obj.__module__}.{obj.__qualname__}" # type: ignore[union-attr]
        if type(obj) in (list, tuple, set, frozenset):
            return repr(type(obj)(ReprWrapper(item, self._repr) for item in obj))
        if type(obj) is dict:
            return repr({ReprWrapper(k, self._repr) :ReprWrapper(v, self._repr)
                         for k,v in obj.items()})
        return repr(obj)

    def aot(self, function_or_type):
        name = function_or_type.__name__
        source = get_source(function_or_type)
        if source is None:
            raise ValueError(f"{name} has no sources")
        if name not in self._added_symbols: # 避免重复定义
            self._codes.append(source)
        self._exported_names.add(name)
        self._orig_module_names[name] = self._scope["__name__"]

        if isinstance(function_or_type, type):
            self._has_class_in_source = True
        if self._has_class_in_source:
            return None # 调用compile()后再写回self._scope

        @functools.wraps(function_or_type) # type: ignore[arg-type]
        def wrapper(*args, **kw):
            if self._comp_thread is None:
                raise RuntimeError(f"Call start_compilation() before calling {name}")
            self._comp_thread.join()
            if self._scope[name] is wrap:
                raise ValueError("compilation is not successful")
            return self._scope[name](*args, **kw)

        wrap = wrapper # wrap: 避免attribute 'wrapper' of 'aot_Compiler_env' undefined
        return wrapper
    def add_func_or_class(self, source: str):
        name = parse_name_from_source(source)
        self._exported_names.add(name)
        self._orig_module_names[name] = self._scope["__name__"]
        self._codes.append(source)
    def add_source(self, source: str):
        self._codes.append(source)

    def get_source_code(self):
        return "\n".join(self._codes)
    def compile(self):
        try:
            if self._custom_compiler is not None:
                init_custom_unix_compiler(self._custom_compiler["cc"],
                                          self._custom_compiler["cxx"])
            if self._cache_dir is None:
                module = mypyc_aot_nocache(self.get_source_code(), quiet=self._quiet,
                                        compiler=self._compiler, **self._kw_options)
            else:
                module = mypyc_aot(self.get_source_code(), cache_dir=self._cache_dir,
                                quiet=self._quiet, compiler=self._compiler,
                                **self._kw_options)
            # 写回self._scope命名空间
            for name in self._exported_names:
                self._scope[name] = getattr(module, name)
                if name in self._orig_module_names:
                    try: # 尝试保持编译后模块名不变
                        self._scope[name].__module__ = self._orig_module_names[name]
                    except Exception: pass
        finally:
            if self._custom_compiler is not None:
                restore_default_compiler()
    def start_compilation_thread(self):
        if self._has_class_in_source:
            raise ValueError("""start_compilation_thread() is disabled when \
classes are used. Use compile() instead.""")
        self._comp_thread = threading.Thread(target=self.compile, daemon=True)
        self._comp_thread.start()
    def use_custom_compiler(self, cc: str, cxx: str):
        self._custom_compiler = {"cc": cc, "cxx": cxx}

# 自举
#if hasattr(get_source, "__code__"):
#    c = Compiler(globals(), ignore_self=False)
#    Compiler = c.aot(Compiler)
#    c.compile()
