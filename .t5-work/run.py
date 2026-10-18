import os, pathlib, runpy, sys, tempfile, uuid
root = pathlib.Path(__file__).resolve().parent
runtime = root / 'runtime'
runtime.mkdir(exist_ok=True)
def mkdtemp(suffix=None, prefix=None, dir=None):
    path = runtime / ((prefix or 'tmp') + uuid.uuid4().hex + (suffix or ''))
    path.mkdir()
    return str(path)
tempfile.mkdtemp = mkdtemp
tempfile.tempdir = str(runtime)
sys.argv = sys.argv[1:]
sys.path.insert(0, str(pathlib.Path(sys.argv[0]).resolve().parent.parent))
runpy.run_path(sys.argv[0], run_name='__main__')
