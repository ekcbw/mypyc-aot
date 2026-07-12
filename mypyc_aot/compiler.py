import os, re, ast, inspect, warnings, builtins
import functools, itertools, threading
from types import NoneType, GenericAlias
from typing import Any, _Final, TypeVar
from librt.random import Random
from librt.strings import BytesWriter, StringWriter
from librt.vecs import vec
from .mypyc_aot import mypyc_aot_nocache, mypyc_aot, CACHE_DIR
from .unix_compiler_util import init_custom_unix_compiler, restore_default_compiler

__all__ = ["Compiler"]

VecGenericAliasType = type(vec[vec[bool]])
DEFAULT_TYPEVAR = TypeVar("DEFAULT_TYPEVAR")

AOT_PATTERN = re.compile(r"^@([0-9A-Za-z_]+?)\.aot[^\n]*?\n")
VALUE_NAME_PATTERN = re.compile(r"^([0-9A-Za-z_]+).*")
IGNORED_NAMES = ["__annotations__", "__builtins__", "__cached__",
                 "__loader__", "__spec__", "__warningregistry__"]
BASIC_TYPES = {int, float, str, bytes, bytearray, list,
               tuple, dict, set, type(None), type(range(0)), slice}
FORMATTABLE_TYPES = {re.Pattern, TypeVar, VecGenericAliasType}
INTERNAL_TYPES = {VecGenericAliasType}
MODULE_MAP: dict[Any, Any] = { # 没有__module__属性的对象
    BytesWriter: "librt.strings", StringWriter: "librt.strings",
    Random: "librt.random", vec: "librt.vecs", NoneType: "types",
}

def is_formattable(obj): # 检查对象能否被Compiler._repr格式化
    # obj为非闭包类
    if isinstance(obj, (type, _Final)) and \
        obj.__name__ == obj.__qualname__: # type: ignore[union-attr]
        return True
    elif type(obj) in BASIC_TYPES: # 不使用isinstance（由于不能是基本类型子类）
        if type(obj) in (list, tuple, dict, set, frozenset):
            if isinstance(obj, dict):
                obj = itertools.chain(obj.keys(), obj.values())
            return all(is_formattable(sub) for sub in obj) # type: ignore
        return True
    elif type(obj) in FORMATTABLE_TYPES:
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

def detect_module(obj) -> str:
    if not isinstance(obj, type):
        return MODULE_MAP.get(obj, obj.__module__)
    if obj.__module__ == "builtins" and obj not in vars(builtins).values():
        for cls in obj.__mro__:
            if cls in MODULE_MAP:
                return MODULE_MAP[cls]
    return obj.__module__

class Compiler:
    _scope: dict
    _added_symbols: set[str]
    _cache_dir: str | None
    _quiet: bool
    _no_symbol_warnings: bool
    _compiler: str | None
    _ignore_import_not_found: bool
    _ignore_self: bool
    _custom_compiler: dict[str, str] | None
    _codes: list[str]
    _comp_thread: threading.Thread | None
    _modules: set[str] # add_symbols_from中临时使用
    _compile_name_map: dict[str, str]
    _orig_module_names: dict[str, str] # 函数/类编译前的模块名（__module__）
    _has_class_in_source: bool
    def __init__(self, scope: dict, ignored_vars: list[str] | None = None,
                 cache_dir=CACHE_DIR, quiet=True, compiler=None,
                 no_symbol_warnings=False, ignore_import_not_found=True,
                 ignore_self=True, **kw):
        self._scope = scope
        self._cache_dir = cache_dir
        self._quiet = quiet
        self._no_symbol_warnings = no_symbol_warnings
        self._compiler = compiler
        self._ignore_import_not_found = ignore_import_not_found
        self._ignore_self = ignore_self
        self._kw_options = kw
        self._custom_compiler = None
        self._codes = []
        self._comp_thread = None
        self._added_symbols = set()
        self._modules = set()
        self._compile_name_map = {} # 编译前后的名称映射
        self._orig_module_names = {} # 用于还原编译前的__module__
        self._has_class_in_source = False
        self.add_symbols_from(self._scope, ignored_vars,
                              self._no_symbol_warnings)
    def add_symbols_from(self, scope: dict, ignored_vars: list[str] | None = None,
                         no_warnings = False, update = True):
        if ignored_vars is None: ignored_vars = []
        annotations: dict[str, Any] = self._scope.get("__annotations__",{})

        for name, value in list(scope.items()): # scope可能会改变大小
            if name in IGNORED_NAMES or name in ignored_vars:
                continue
            if not update and name in self._added_symbols:
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
                    comment = " # type: ignore[import-not-found]" \
                              if self._ignore_import_not_found else ""
                    self._codes.append(f"import {value.__name__} as {name}{comment}")
            elif (isinstance(value, type) or inspect.isfunction(value) \
                or inspect.isbuiltin(value)) and value not in INTERNAL_TYPES:
                module_name = detect_module(value)
                if self._ignore_self and module_name.startswith("mypyc_aot"):
                    continue
                if module_name == scope["__name__"]: # 在scope本身
                    source = get_source(value)
                    if source is not None:
                        self._codes.append(source)
                        continue
                self._orig_module_names[name] = module_name

                name_match = re.match(VALUE_NAME_PATTERN, value.__name__)
                value_name = name_match.group(1) if name_match is not None \
                             else value.__name__
                comment = " # type: ignore[import-not-found]" \
                          if self._ignore_import_not_found else ""
                self._codes.append(
                    f"from {module_name} import {value_name} as {name}{comment}")
            elif is_formattable(value):
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
    def _repr(self, obj) -> str: # 格式化对象，同时检测模块
        if obj is NoneType:
            return "type(None)"
        if obj is VecGenericAliasType or isinstance(obj, VecGenericAliasType):
            return self.format_vec_generic(obj)

        if type(obj) is GenericAlias:
            if not isinstance(obj.__args__, tuple):
                args_str = self._repr(obj.__args__)
            else:
                args_str = ", ".join(self._repr(arg) for arg in obj.__args__)
            return f"{self._repr(obj.__origin__)}[{args_str}]"
        if type(obj) is TypeVar:
            self._modules.add("typing")
            return self.format_typevar(obj)
        if isinstance(obj, (type, _Final)): # 类型对象
            module_name = detect_module(obj)
            self._modules.add(module_name) # type: ignore[union-attr]
            return f"{module_name}.{obj.__qualname__}" # type: ignore[union-attr]
        if type(obj) in (list, tuple): # type(obj)：不包含子类
            return repr(type(obj)(ReprWrapper(item, self._repr) for item in obj))
        if type(obj) in (set, frozenset):
            pieces = ", ".join(sorted(self._repr(item) for item in obj)) # 顺序确定的格式化
            if type(obj) is set:
                return f"{{{pieces}}}"
            else:
                return f"frozenset({pieces})"
        if type(obj) is dict:
            return repr({ReprWrapper(k, self._repr) :ReprWrapper(v, self._repr)
                         for k,v in obj.items()})
        return repr(obj)
    def format_typevar(self, t: TypeVar) -> str:
        attr_map = {
            "__bound__": "bound",
            "__contravariant__": "contravariant",
            "__covariant__": "covariant",
            "__infer_variance__": "infer_variance",
            "__default__": "default",
        }
        args: dict[str, str] = {}
        for attr, arg_name in attr_map.items():
            if hasattr(t, attr):
                value = getattr(t, attr)
                if value == getattr(DEFAULT_TYPEVAR, attr): continue
                args[arg_name] = self._repr(value)
        if args:
            kwarg_str = ", " + ", ".join(
                f"{name}={value}" for name, value in args.items())
        else:
            kwarg_str = ""
        if t.__constraints__:
            arg_str = ", " + ", ".join(
                self._repr(item) for item in t.__constraints__)
        else:
            arg_str = ""
        return f"typing.TypeVar({t.__name__!r}{arg_str}{kwarg_str})"
    def format_vec_generic(self, obj):
        # VecGenericAliasType的逻辑
        code = "from librt.vecs import vec"
        if code not in self._codes:
            self._codes.append(code)
        if obj is VecGenericAliasType:
            return "type(vec[vec[bool]])"
        else:
            # VecGenericAliasType未实现获取内部类型的属性
            match = re.match(r"<class_proxy '(.*)'>", repr(obj)) # 类型（如u8）已出现在self._scope，无需导入
            if match is None:
                return repr(obj)
            return match.group(1)

    def aot(self, function_or_class, new_name=None, wait=True):
        name = function_or_class.__name__
        if new_name is None:
            new_name = name
        source = get_source(function_or_class)
        if source is None:
            raise ValueError(f"{name} has no sources")
        if name not in self._added_symbols: # 避免重复定义
            self._codes.append(source)
        self._added_symbols.add(name)
        self._compile_name_map[name] = new_name
        self._orig_module_names[name] = self._scope["__name__"]

        if isinstance(function_or_class, type):
            self._has_class_in_source = True
        if self._has_class_in_source:
            return None # 类在调用compile()后写回self._scope

        @functools.wraps(function_or_class) # type: ignore[arg-type]
        def wrapper(*args, **kw):
            if self._comp_thread is None:
                raise RuntimeError(
                    f"Call compile() or start_compilation_thread() before calling {new_name}")
            if wait:
                self._comp_thread.join()
            if self._scope[new_name] is wrap: # 尚未编译完成
                if not self._comp_thread.is_alive():
                    raise ValueError("compilation not successful")
                return function_or_class(*args, **kw)
            return self._scope[new_name](*args, **kw) # 调用已编译的函数

        wrap = wrapper # wrap: 避免attribute 'wrapper' of 'aot_Compiler_env' undefined
        return wrapper
    def add_func_or_class(self, source: str):
        name = parse_name_from_source(source)
        self._compile_name_map[name] = name
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
            for name, new_name in self._compile_name_map.items():
                self._scope[new_name] = getattr(module, name)
                if name in self._orig_module_names:
                    try: # 尝试还原编译前的__module__
                        self._scope[new_name].__module__ = self._orig_module_names[name]
                    except Exception:
                        pass
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

if os.getenv("MYPYC_AOT_BOOTSTRAP") == "1" and \
    not "__mypyc_aot_path__" in globals(): # 设置了MYPYC_AOT_BOOTSTRAP且自身未被编译
    c = Compiler(globals(), ignore_self=False)
    Compiler = c.aot(Compiler) # type: ignore
    c.compile()
