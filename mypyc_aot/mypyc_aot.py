import sys, os, io, string, base64, random, shutil
import pickle, sysconfig, tempfile, threading
from hashlib import sha256
import subprocess
try:
    import distutils.compilers.C.base as _base
except ImportError:
    import distutils.ccompiler as _base
from setuptools import setup
from mypy.defaults import CACHE_DIR as _mypy_cache_basename
from mypyc.build import mypycify

__all__ = ["mypyc_aot_nocache", "mypyc_aot", "clear_all_cache",
           "clear_intermediate_cache"]
_home = os.environ["USERPROFILE"] if sys.platform == "win32" \
        else os.environ["HOME"]
CACHE_DIR = os.path.join(_home, ".mypyc_aot_cache")
try:
    __import__("zstandard")
    DEFAULT_COMP_METHOD = "zstandard"
except ImportError:
    try:
        __import__("zlib")
        DEFAULT_COMP_METHOD = "zlib"
    except ImportError:
        DEFAULT_COMP_METHOD = None

_config = {}

class RedirectedStream:
    def __init__(self, orig_stream, stream):
        self.orig_stream = orig_stream
        self.stream = stream
        self.thread_id = threading.get_ident()
    def write(self, data):
        if threading.get_ident() == self.thread_id: # 是当前线程
            return self.stream.write(data)
        else:
            return self.orig_stream.write(data)
    def __getattr__(self, attr):
        return getattr(self.orig_stream, attr) # 返回orig_stream的属性和方法

class NoCompression:
    @staticmethod
    def compress(data: bytes) -> bytes: return data
    @staticmethod
    def decompress(data: bytes) -> bytes: return data

def rand_name(length):
    chars = string.ascii_letters + string.digits
    return "".join(chars[random.randrange(len(chars))] for _ in range(length))

def set_default_compiler(compiler: str | None):
    if compiler is None:
        del _config["default_compiler"]
    else: _config["default_compiler"] = compiler

def get_module_path(module_name):
    for finder in sys.meta_path:
        spec = finder.find_spec(module_name, sys.path)
        if spec is not None:
            return spec.origin
    return None

def captured_popen(stream):
    class Popen(subprocess.Popen):
        def __init__(self, *args, **kw):
            kw.setdefault("stdout", subprocess.PIPE)
            kw.setdefault("stderr", subprocess.PIPE)
            return super().__init__(*args, **kw)
        def wait(self, *args, **kw):
            result = super().wait(*args, **kw)
            if self.stdout is None or self.stderr is None:
                return result
            if not self.stdout.closed and not self.stderr.closed:
                # _communicate: 避免递归
                stdout, stderr = self._communicate(None, None, None) # type: ignore
                if stdout is not None:
                    stream.write(stdout.decode("utf-8", "replace"))
                if stderr is not None:
                    stream.write(stderr.decode("utf-8", "replace"))
            return result
    return Popen

def mypyc_aot_nocache(pycode: str, prefix="mypyc_aot", cache_dir = None,
                      quiet=True, compiler: str | None = None,
                      opt_level="3", strict_dunder_typing=True,
                      experimental_features=False, debug_level="0",
                      **kw):
    if cache_dir is None:
        temp_dir = tempfile.gettempdir()
    else:
        temp_dir = os.path.join(cache_dir, "cache")
    random_name = rand_name(16)
    py_path = os.path.join(temp_dir, f"{random_name}-mypyc-aot")
    os.makedirs(py_path, exist_ok=True)

    mod_name = f"{prefix}_{random_name}"
    pyfile = os.path.join(py_path, f"{mod_name}.py")
    with open(pyfile, "w", encoding="utf-8") as f:
        f.write(pycode)

    prev_argv = sys.argv.copy()
    prev_path = sys.path.copy()
    prev_stdout, prev_stderr = sys.stdout, sys.stderr
    prev_mypy_cache_dir = os.getenv("MYPY_CACHE_DIR")
    prev_cwd = os.getcwd()
    _Popen = subprocess.Popen
    _get_default_compiler = _base.get_default_compiler
    stream = io.StringIO()
    try:
        if quiet:
            subprocess.Popen = captured_popen(stream) # 重定向子进程的输出
        if compiler is None and _config.get("default_compiler"):
            compiler = _config["default_compiler"]
        if compiler is not None:
            def get_default_compiler(*args, **kw):
                return compiler
            _base.get_default_compiler = get_default_compiler

        if cache_dir is not None:
            os.environ["MYPY_CACHE_DIR"] = os.path.join(cache_dir,
                                                        _mypy_cache_basename)
        sys.argv[1:] = ["build_ext", "--inplace"]
        if quiet:
            sys.argv.append("-q")
        sys.stdout = RedirectedStream(sys.stdout, stream)
        sys.stderr = RedirectedStream(sys.stderr, stream)
        os.chdir(py_path)
        new_sys_path = [*sys.path, py_path]
        sys.path = new_sys_path
        try:
            setup(
                name = mod_name,
                ext_modules = mypycify([pyfile, "--check-untyped-defs"],
                                       opt_level=opt_level,
                                       strict_dunder_typing=strict_dunder_typing,
                                       experimental_features=experimental_features,
                                       debug_level=debug_level, **kw),
            )
        except SystemExit as err:
            sys.stdout, sys.stderr = prev_stdout, prev_stderr
            if err.code != 0:
                raise RuntimeError(
                    f"Nonzero exit ({err.code}), outputs:\n{stream.getvalue()}")\
                    from None

        sys.path = new_sys_path
        module =  __import__(mod_name)
        module.__mypyc_aot_path__ = get_module_path(mod_name)
        return module
    finally:
        sys.argv = prev_argv
        sys.path = prev_path
        sys.stdout, sys.stderr = prev_stdout, prev_stderr
        os.chdir(prev_cwd)
        subprocess.Popen = _Popen
        _base.get_default_compiler = _get_default_compiler
        if prev_mypy_cache_dir is not None:
            os.environ["MYPY_CACHE_DIR"] = prev_mypy_cache_dir
        else: del os.environ["MYPY_CACHE_DIR"]

def mypyc_aot(pycode, prefix="mypyc_aot", cache_dir=CACHE_DIR,
              compression_method=DEFAULT_COMP_METHOD, **kw):
    try:
        if compression_method is None:
            mod = NoCompression
        else:
            mod = __import__(compression_method)
        assert mod.decompress(mod.compress(b"")) == b""
    except Exception as err:
        raise ValueError(f"""{compression_method!r} should be a module with \
reversible compress() and decompress() function:
{type(err).__name__}: {err}""") from None

    ext_suffix = sysconfig.get_config_var('EXT_SUFFIX')
    hash = base64.urlsafe_b64encode(sha256(
        f"{pycode} {ext_suffix} {kw!r} {_config!r}".encode()
        ).digest()).decode()
    cache_file = os.path.join(cache_dir, f"{hash}.{compression_method}")

    if os.path.isfile(cache_file): # 加载缓存
        with open(cache_file, "rb") as f:
            data = pickle.loads(mod.decompress(f.read()))
        py_path = os.path.join(cache_dir, "cache",
                               f"{hash}{compression_method}-lib")
        os.makedirs(py_path, exist_ok=True)
        filename = os.path.join(py_path, data["name"])
        if not os.path.isfile(filename):
            with open(filename, "wb") as f:
                f.write(data["data"])

        prev_path = sys.path.copy()
        try:
            sys.path.append(py_path)
            module = __import__(data["name"].split(".")[0])
            module.__mypyc_aot_path__ = filename
            return module
        finally:
            sys.path = prev_path
    else:
        compiled = mypyc_aot_nocache(pycode, prefix, cache_dir, **kw)
        with open(compiled.__mypyc_aot_path__, "rb") as f:
            data = f.read()
        with open(cache_file, "wb") as f:
            f.write(mod.compress(
                pickle.dumps({
                    "name": os.path.basename(compiled.__mypyc_aot_path__),
                    "data": data
                })
            ))
        return compiled

def clear_all_cache():
    if os.path.isdir(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)

def clear_intermediate_cache():
    # 仅清理中间产物，不清理缓存
    if os.path.isdir(os.path.join(CACHE_DIR, "cache")):
        shutil.rmtree(os.path.join(CACHE_DIR, "cache"))
    if os.path.isdir(os.path.join(CACHE_DIR, ".mypy_cache")):
        shutil.rmtree(os.path.join(CACHE_DIR, ".mypy_cache"))
