#!/usr/bin/env python3

from typing import Optional
from smx_analysis import CompilationConfig, RunCommandError, run_or_fail, eprint, log_temp, walk_files
import tempfile
import uuid
import os
import multiprocessing
import functools


def compile_src(src_file: str, dir: str, config: CompilationConfig,
                smx_lib: str, pic: bool) -> Optional[str]:
  '''
  Compiles the given source file.
  
  Returns the path to the compiled object file on success,
  otherwise `None`.
  '''
  # compile to LLVM IR
  ll = config.compile(dir, src_file)
  # insert profiling functions
  loop_profiler_flags = f'-load-pass-plugin={smx_lib} -passes=loop-profiler'
  ll_simplified = run_or_fail(f'opt -S -loop-simplify', stdin=ll)
  try:
    ll_prof = run_or_fail(f'opt -S {loop_profiler_flags}', stdin=ll_simplified)
  except RunCommandError as e:
    temp = log_temp(ll_simplified, prefix='lp-', suffix='.ll')
    eprint('Error occurred when running loop profiler pass!')
    eprint(f'The LLVM IR file has already been dumped to "{temp}".')
    return None
  # compile to object
  pic_flag = '-relocation-model=pic' if pic else ''
  obj_file = os.path.join(tempfile.gettempdir(), f'{uuid.uuid1()}.o')
  run_or_fail(f'llc -filetype=obj {pic_flag} -O3 -o {obj_file}', stdin=ll_prof)
  return obj_file


def compile_dir(dir_name: str, dir: str, exe_file: str, config: CompilationConfig,
                smx_lib: str, libprof: str, pic: bool) -> None:
  '''
  Compiles all source files in the given directory
  and save the compiled executable to the given file.
  '''
  # scan for all source files
  src_files = []
  dir = os.path.abspath(dir)
  for root, files in walk_files(config, dir_name, dir):
    for f in files:
      if config.is_source(dir_name, f):
        src_files.append(os.path.abspath(os.path.join(root, f)))
  if not src_files:
    return
  # compile to object files
  with multiprocessing.Pool() as p:
    f = functools.partial(compile_src, dir=dir,
                          config=config, smx_lib=smx_lib, pic=pic)
    objs = []
    for obj in p.map(f, src_files):
      if obj is None:
        raise RuntimeError(f'failed to compile "{dir_name}"')
      else:
        objs.append(obj)
  # link to executable
  config.link(objs, exe_file, flags=libprof)
  for obj in objs:
    os.remove(obj)


def compile_root(root: str, out_dir: str, config: CompilationConfig,
                 smx_lib: str, libprof: str, pic: bool) -> None:
  '''
  Compiles the given root directory
  and save the compiled executable to the output directory.
  '''
  dirs = []
  for dir in os.listdir(root):
    dir_path = os.path.join(root, dir)
    if os.path.isdir(dir_path):
      dirs.append((dir, dir_path))
  for i, (dir, dir_path) in enumerate(dirs):
    exe_file = os.path.join(out_dir, dir)
    if os.path.exists(exe_file):
      eprint(f'[{i + 1}/{len(dirs)}] Skipped "{dir}"')
    else:
      eprint(f'[{i + 1}/{len(dirs)}] Compiling "{dir}" ...')
      compile_dir(dir, dir_path, exe_file, config, smx_lib, libprof, pic)


if __name__ == '__main__':
  import argparse
  parser = argparse.ArgumentParser(
      description='Compiler for inserting loop profiler to projects/repositories.')
  parser.add_argument('root', type=str, help='project root directory')
  parser.add_argument('-c', '--config', type=str, required=True,
                      help='compilation configuration')
  parser.add_argument('-sl', '--smx-lib', type=str, required=True,
                      help='SMX transforms library')
  parser.add_argument('-pl', '--libprof', type=str, required=True,
                      help='profiling library')
  parser.add_argument('-pic', default=False, action='store_true',
                      help='generate PIC')
  parser.add_argument('-d', '--dir', type=str, default=None,
                      help='specify the directory to compile')
  parser.add_argument('-o', '--output', type=str, default=None,
                      help='output directory, default to CWD')

  args = parser.parse_args()
  config = CompilationConfig(args.config)
  if args.output is None:
    out_dir = os.path.curdir
  else:
    out_dir = args.output
    if not os.path.isdir(out_dir):
      eprint(f'invalid output directory "{out_dir}"')
      exit(-1)

  if args.dir is None:
    compile_root(args.root, out_dir, config,
                 args.smx_lib, args.libprof, args.pic)
  else:
    dir_path = os.path.join(args.root, args.dir)
    if not os.path.isdir(dir_path):
      eprint(f'invalid directory "{dir_path}"')
      exit(-1)
    dir_name = os.path.basename(dir_path)
    exe_file = os.path.join(out_dir, dir_name)
    compile_dir(dir_name, dir_path, exe_file, config,
                args.smx_lib, args.libprof, args.pic)
