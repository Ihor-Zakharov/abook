import importlib.machinery, importlib.util, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
def load(db):
    loader = importlib.machinery.SourceFileLoader("abookmod", os.path.join(os.path.dirname(os.path.abspath(__file__)), "abook"))
    spec = importlib.util.spec_from_loader("abookmod", loader); m = importlib.util.module_from_spec(spec); loader.exec_module(m)
    class Args: pass
    a = Args(); a.db = db; a.out_dir = None
    m._configure_db_paths(a)
    return m
