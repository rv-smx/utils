#!/usr/bin/env python3

from typing import Optional, List, Any, Dict, Tuple, Iterator
import subprocess
import shlex
import os
from os import path
import json
import sys
import tempfile
import multiprocessing
import functools
from queue import Queue


class RunCommandError(Exception):
  '''
  Exception that indicates error when running a command line.
  '''
  pass


def run_or_fail(cmd: str, stdin: Optional[str] = None, cwd: Optional[str] = None,
                capture_stderr: bool = False) -> str:
  '''
  Runs the given command line, raise `RunCommandError` if error returned.

  Returns the standard output.
  '''
  ret = subprocess.run(shlex.split(cmd), input=stdin, cwd=cwd,
                       capture_output=True, text=True)
  if ret.returncode:
    raise RunCommandError(f'failed to run "{cmd}", returned {ret.returncode}')
  return ret.stderr if capture_stderr else ret.stdout


class CompilationConfig:
  '''
  Compilation configuration.
  '''

  def __init__(self, config_file: str) -> None:
    with open(config_file) as f:
      self.__config = json.load(f)

  def __ext_cfg(self, ext: str) -> Optional[str]:
    return self.__config['extensionMap'].get(ext.lower())

  def __dir_config(self, dir_name: str) -> Dict[str, Any]:
    return self.__config['directoryConfigs'].get(dir_name, {})

  def __get_compile_cmd(self, dir_name: str, ext: str) -> str:
    cfg = self.__ext_cfg(ext)
    if cfg is None:
      raise RuntimeError(f'unknown extension "{ext}"')
    cmd = self.__config['configs'][cfg]
    flags = self.__dir_config(dir_name).get('flags', {}).get(cfg)
    if flags is not None:
      return f'{cmd} {flags}'
    return cmd

  def is_source(self, dir_name: str, file: str) -> bool:
    '''
    Returns `True` if the given file is a valid source file.
    '''
    ext = path.splitext(file)[-1][1:]
    cfg = self.__ext_cfg(ext)
    if cfg is None:
      return False
    ignore = self.__dir_config(dir_name).get('ignore', {})
    if cfg in ignore.get('configs', []):
      return False
    for f in ignore.get('files', []):
      if file.endswith(f):
        return False
    return True

  def should_ignore_dir(self, dir_name: str, root: str, dir: str) -> bool:
    '''
    Returns `True` if the given directory should be ignored.
    '''
    ignore = self.__dir_config(dir_name).get('ignore', {})
    dir = path.abspath(path.join(root, dir))
    for d in ignore.get('directories', []):
      if dir == path.abspath(path.join(root, d)):
        return True
    return False

  def compile(self, cwd: str, src_file: str) -> str:
    '''
    Compiles the given source file to LLVM IR file.

    Returns the compiled LLVM IR.
    '''
    dir_name = path.basename(cwd)
    ext = path.splitext(src_file)[-1][1:]
    cmd = self.__get_compile_cmd(dir_name, ext)
    return run_or_fail(f'{cmd} {src_file} -o -', cwd=cwd)

  def link(self, objs: List[str], exe_file: str, cwd: Optional[str] = None,
           flags: str = '') -> None:
    '''
    Linkes the given object files to executable.
    '''
    obj_list = ' '.join(objs)
    cmd = self.__config['linker']
    run_or_fail(f'{cmd} {flags} {obj_list} -o {exe_file}', cwd=cwd)


def eprint(*args, **kwargs) -> None:
  '''
  Prints to `stderr`.
  '''
  print(*args, file=sys.stderr, **kwargs)
  sys.stderr.flush()


def log_temp(content: str, prefix: str = 'smxa-',
             suffix: Optional[str] = None) -> str:
  '''
  Logs the given content to a temporary file, returns the file name.
  '''
  fd, temp = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir='.')
  with os.fdopen(fd, 'w') as f:
    f.write(content)
  return temp


def walk_files(config: CompilationConfig, dir_name: str,
               root: str) -> Iterator[Tuple[str, List[str]]]:
  '''
  Walks the given root directory, ignores directories that
  marked as ignored in the configuration.

  Returns an iterator of tuple of current root and file list.
  '''
  q = Queue()
  q.put('.')
  while not q.empty():
    cur_root = q.get()
    full_root = path.join(root, cur_root)
    files = []
    for f in os.listdir(full_root):
      if path.isfile(path.join(full_root, f)):
        files.append(f)
      else:
        next_root = path.join(cur_root, f)
        if not config.should_ignore_dir(dir_name, root, next_root):
          q.put(next_root)
    yield (full_root, files)


def analyse(ll: str, smx_lib: str, passes: str) -> List[Any]:
  '''
  Analyses the given LLVM IR and returns the result.
  '''
  pass_flags = f'-load-pass-plugin={smx_lib} -passes="{passes}"'
  flags = f'{pass_flags} -disable-output -march=rv64gc_xsmx'
  try:
    out = run_or_fail(f'opt {flags}', stdin=ll, capture_stderr=True)
  except RunCommandError as e:
    temp = log_temp(ll, suffix='.ll')
    eprint(f'Error occurred when running passes "{passes}"!')
    eprint(f'The LLVM IR file has already been dumped to "{temp}".')
    raise e
  result = []
  try:
    for line in out.splitlines():
      result.append(json.loads(line))
  except json.JSONDecodeError as e:
    temp = log_temp(out, suffix='.json')
    eprint('Error occurred when parsing JSON result!')
    eprint(f'The analysis output has already been dumped to "{temp}".')
    raise e
  return result


def analyse_src(src_file: str, dir: str, config: CompilationConfig,
                smx_lib: str) -> Tuple[List[Any], List[Any]]:
  '''
  Analyses the given source file and return the result.
  '''
  ll = config.compile(dir, src_file)
  ll = run_or_fail('opt -S -passes="loop-simplify,instnamer" -march=rv64gc_xsmx',
                   stdin=ll)
  smx_result = analyse(ll, smx_lib, 'print<stream-memory>')
  loop_tree_result = analyse(ll, smx_lib, 'print<loop-trees>')
  return smx_result, loop_tree_result


def analyse_dir(dir_name: str, dir: str, config: CompilationConfig,
                smx_lib: str) -> Tuple[List[Any], Dict[str, Any]]:
  '''
  Analyses all of the C files in the given directory
  and returns the result.
  '''
  # collect source files
  src_files = []
  dir = path.abspath(dir)
  for root, files in walk_files(config, dir_name, dir):
    for f in files:
      if config.is_source(dir_name, f):
        src_files.append(path.abspath(path.join(root, f)))
  # run analysis
  with multiprocessing.Pool(multiprocessing.cpu_count()) as p:
    f = functools.partial(analyse_src, dir=dir, config=config, smx_lib=smx_lib)
    results = p.map(f, src_files)
  # process results
  smx_result = []
  loop_tree_result = {}
  for smx, loop_tree in results:
    for record in smx:
      smx_result += record
    for record in loop_tree:
      for k, v in record.items():
        loop_tree_result.setdefault(k, []).append(v)
  return smx_result, loop_tree_result


def analyse_root(root: str, out_dir: str, config: CompilationConfig, smx_lib: str) -> None:
  '''
  Analyses the given root directory
  and save results to the give output directory.
  '''
  dirs = []
  for dir in os.listdir(root):
    dir_path = path.join(root, dir)
    if path.isdir(dir_path):
      dirs.append((dir, dir_path))
  for i, (dir, dir_path) in enumerate(dirs):
    smx_out_file = path.join(out_dir, f'{dir}.smx.json')
    loop_tree_out_file = path.join(out_dir, f'{dir}.loops.json')
    if path.exists(smx_out_file) and path.exists(loop_tree_out_file):
      eprint(f'[{i + 1}/{len(dirs)}] Skipped "{dir}"')
    else:
      eprint(f'[{i + 1}/{len(dirs)}] Analysing "{dir}" ...')
      smx_result, loop_tree_result = analyse_dir(dir, dir_path,
                                                 config, smx_lib)
      with open(smx_out_file, 'w') as f:
        json.dump(smx_result, f)
      with open(loop_tree_out_file, 'w') as f:
        json.dump(loop_tree_result, f)


if __name__ == '__main__':
  import argparse
  parser = argparse.ArgumentParser(
      description='SMX analysis for projects/repositories.')
  parser.add_argument('root', type=str, help='project root directory')
  parser.add_argument('-c', '--config', type=str, required=True,
                      help='compilation configuration')
  parser.add_argument('-l', '--lib', type=str, required=True,
                      help='SMX transforms library')
  parser.add_argument('-d', '--dir', type=str, default=None,
                      help='specify the directory to analyse')
  parser.add_argument('-o', '--output', type=str, default=None,
                      help='output directory, default to CWD')

  args = parser.parse_args()
  config = CompilationConfig(args.config)
  if args.output is None:
    out_dir = path.curdir
  else:
    out_dir = args.output
    if not path.isdir(out_dir):
      eprint(f'invalid output directory "{out_dir}"')
      exit(-1)

  if args.dir is None:
    analyse_root(args.root, out_dir, config, args.lib)
  else:
    dir_path = path.join(args.root, args.dir)
    if not path.isdir(dir_path):
      eprint(f'invalid directory "{dir_path}"')
      exit(-1)
    dir_name = path.basename(dir_path)
    result = analyse_dir(dir_name, dir_path, config, args.lib)
    with open(path.join(out_dir, f'{dir_name}.json'), 'w') as f:
      json.dump(result, f)
