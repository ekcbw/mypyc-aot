import os, sysconfig
import distutils.sysconfig as distutils_sysconfig
from .mypyc_aot import set_default_compiler

__all__ = ["init_custom_unix_compiler", "restore_default_compiler"]
_original_env = {}

def init_custom_unix_compiler(cc: str, cxx: str):
    # 自定义C/C++编译器，不依赖sysconfig中的配置
    # cc为"gcc" / "clang"，cxx为"g++" / "clang++"
    env_vars = {
        "CC": cc,
        "CXX": cxx,
        "LDSHARED": f"{cc} -shared",
        "AR": "ar",
        "ARFLAGS": ""
    }
    sysconfig_vars = {
        "CCSHARED": "-shared",
        "CFLAGS": "-s -O2 -Wall -pipe"
    }

    for var in env_vars.keys():
        if var in os.environ:
            _original_env.setdefault(var, os.environ[var])
        else:
            _original_env.setdefault(var, None)
    os.environ.update(env_vars)

    if distutils_sysconfig._config_vars is None:
        distutils_sysconfig._config_vars = sysconfig.get_config_vars().copy()
    distutils_sysconfig._config_vars.update(sysconfig_vars)
    set_default_compiler("unix")

def restore_default_compiler():
    for var, value in _original_env.items():
        if value is None:
            if var in os.environ:
                del os.environ[var]
        else:
            os.environ[var] = value
    _original_env.clear()
    
    distutils_sysconfig._config_vars = sysconfig.get_config_vars().copy()
    set_default_compiler(None)
