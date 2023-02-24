#!/usr/bin/env python3

from typing import List, Dict, Any, IO, Optional
from result_analysis import StreamInfo
import os
import sys
import json


LoopTree = Dict[str, List[Optional[str]]]
SmxResult = Dict[str, Any]
SmxDict = Dict[str, Dict[str, SmxResult]]
ProfRecord = Dict[str, Any]


def get_loop_id(debug_loc: str) -> str:
  '''
  Returns the loop ID by the given debug location info.
  '''
  path = debug_loc.split('@[')[0].strip()
  id = os.path.basename(path)
  return id


def build_loop_tree(loops_file: str) -> LoopTree:
  '''
  Reads the given `.loops.json` file and returns a loop tree.
  '''
  with open(loops_file, 'r') as f:
    data: LoopTree = json.load(f)
  tree: LoopTree = {}
  for loc, records in data.items():
    id = get_loop_id(loc)
    tree[id] = [None if i is None else get_loop_id(i) for i in records]
  return tree


def build_smx_dict(smx_file: str) -> SmxDict:
  '''
  Reads the given `.smx.json` file and returns a `dict`
  of SMX analysis results.
  '''
  with open(smx_file, 'r') as f:
    data: List[SmxResult] = json.load(f)
  smx_dict: SmxDict = {}
  for result in data:
    loop_info = result['loop']
    id = get_loop_id(loop_info['startLoc'])
    func = loop_info['parentFunc']
    smx_dict.setdefault(id, {})[func] = result
  return smx_dict


class ProfResult:
  '''
  Profiling analysis result.
  '''

  def __init__(self, prof: ProfRecord, smx: Optional[SmxResult]) -> None:
    self.__prof = prof
    self.__streamizable = None
    self.__has_indirect_access = None
    if smx is not None:
      self.__updated_stream_info(smx)

  def __updated_stream_info(self, smx: SmxResult) -> None:
    # get induction variable stream of the profile record's loop
    loop_id = get_loop_id(self.__prof['location'])
    iv_name = None
    for iv in smx['inductionVariableStreams']:
      if get_loop_id(iv['loopStartLoc']) == loop_id:
        iv_name = iv['name']
    if iv_name is None:
      return
    # check if the induction variable stream is supported
    info = StreamInfo(smx)
    self.__streamizable = info.is_supported_iv(iv_name)
    self.__has_indirect_access = False
    if not self.__streamizable:
      return
    # check if there are indirect stream accesses in the loop
    for ms in smx['memStreams']:
      name = ms['name']
      for factor in ms['factors']:
        if factor['depStreamKind'] == 'inductionVariable' \
                and factor['depStream'] == iv_name \
                and info.is_indirect_supported_ms(name):
          self.__has_indirect_access = True
          return

  @staticmethod
  def dump_csv_header(f: IO) -> None:
    '''
    Dumps CSV header to the given file.
    '''
    print('Address', 'Location', 'Function', 'Cache Read MPKI',
          'Cache Write MPKI', 'Average Instructions', 'Number of Executions',
          'Streamizable', 'Has Indirect Stream Access', sep=',', file=f)

  @staticmethod
  def __tri_state_to_str(tri: Optional[bool]) -> str:
    '''
    Returns a string that can represents the given tri-state value.
    '''
    if tri is None:
      return 'undetermined'
    return 'yes' if tri else 'no'

  def dump_csv_line(self, f: IO) -> None:
    '''
    Dumps CSV line of the current result to the given file.
    '''
    p = self.__prof
    print(p['address'], p['location'], p['function'], p['readMpki'],
          p['writeMpki'], p['averageInstructions'], p['numExecutions'],
          self.__tri_state_to_str(self.__streamizable),
          self.__tri_state_to_str(self.__has_indirect_access), sep=',', file=f)


def get_top_level_loop(id: str, loops: LoopTree) -> Optional[str]:
  '''
  Returns the ID of the top level loop of the given loop.

  Returns `None` if the top level loop can not be determined.
  '''
  parents = loops.get(id)
  if parents is None or len(parents) != 1:
    return None
  parent = parents[0]
  if parent is None:
    return id
  return get_top_level_loop(parent, loops)


def get_smx_result_of_loop(id: str, func: str, loops: LoopTree,
                           smxs: SmxDict) -> Optional[SmxResult]:
  '''
  Returns the SMX result of the given loop.

  Returns `None` of the SMX result can not be determined.
  '''
  # try to get result of the current loop
  smx = smxs.get(id)
  if smx is None:
    # get top level loop id
    top_id = get_top_level_loop(id, loops)
    if top_id is None:
      return None
    # get result of the top level loop
    smx = smxs.get(top_id)
    if smx is None:
      return None
  # get result of the function
  return smx.get(func)


def gen_prof_results(profs: List[ProfRecord], loops: LoopTree,
                     smxs: SmxDict) -> List[ProfResult]:
  '''
  Generates a profiling result list by the given profiling results,
  loop tree and SMX results.
  '''
  results = []
  for prof in profs:
    id = get_loop_id(prof['location'])
    func = prof['function']
    smx = get_smx_result_of_loop(id, func, loops, smxs)
    results.append(ProfResult(prof, smx))
  return results


def dump_csv(profs: List[ProfResult], f: IO) -> None:
  '''
  Dumps CSV of the given profiling results to file.
  '''
  ProfResult.dump_csv_header(f)
  for prof in profs:
    prof.dump_csv_line(f)


if __name__ == '__main__':
  import argparse
  parser = argparse.ArgumentParser(description='Loop profile analyser.')
  parser.add_argument('profile', type=str, help='loop profile (JSON)')
  parser.add_argument('smx', type=str, help='SMX analysis result (JSON)')
  parser.add_argument('loops', type=str, help='loop tree (JSON)')
  parser.add_argument('-o', '--output', type=str, default=None,
                      help='specify the output CSV file, default to stdout')
  args = parser.parse_args()

  # load profiling data
  with open(args.profile, 'r') as f:
    profs = json.load(f)
  # build loop tree and SMX analysis result dictionary
  loops = build_loop_tree(args.loops)
  smxs = build_smx_dict(args.smx)
  # generate result
  results = gen_prof_results(profs, loops, smxs)

  # dump CSV to output file
  if args.output is None:
    dump_csv(results, sys.stdout)
  else:
    with open(args.output, 'w') as f:
      dump_csv(results, f)
