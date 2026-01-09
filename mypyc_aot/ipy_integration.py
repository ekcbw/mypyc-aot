import re
from IPython.core.magic import Magics, magics_class, cell_magic
from .compiler import Compiler

IGNORED_NAMES = ["get_ipython", "exit", "quit", "In", "Out",
                 "_ih", "_oh", "_dh", "_", "__", "___", "_i",
                 "_ii", "_iii", "__session__", "__builtin__"]
IGNORED_VAR_PATTERN = re.compile(r"_\d*?|_i\d*?")

@magics_class
class MyPyCAotMagics(Magics):
    def __init__(self, shell):
        super().__init__(shell)
    def _get_ignored_names(self):
        ignored = IGNORED_NAMES.copy()
        for name in self.shell.user_ns:
            if re.match(IGNORED_VAR_PATTERN, name):
                ignored.append(name)
        return ignored
    @cell_magic
    def mypyc_aot(self, line, cell):
        compiler = Compiler(self.shell.user_ns,
                            self._get_ignored_names())
        compiler.add_func_or_class(cell)
        compiler.compile()

def load_ipython_extension(ipython):
    ipython.register_magics(MyPyCAotMagics)
