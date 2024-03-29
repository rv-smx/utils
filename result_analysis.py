#!/usr/bin/env python3

from typing import Dict, Any, List, IO, Optional, Tuple, Set
import json
import os
from dataclasses import dataclass


class StreamInfo:
  '''
  SMX stream information.
  '''

  def __init__(self, info: Dict[str, Any]) -> None:
    # check memory streams
    self.__num_mss = len(info['memStreams'])
    self.__supported_mss = set()
    self.__indirect_supported_mss = set()
    self.__max_num_iv_factors = 0
    self.__max_num_ms_factors = 0
    self.__max_width = 0
    self.__supported_ivs = set()
    self.__check_mss(info)
    # check induction variable streams
    self.__num_ivs = len(info['inductionVariableStreams'])
    self.__max_iv_chain_len = 0
    self.__check_ivs(info)
    # check memory operations
    self.__num_loads = 0
    self.__num_stores = 0
    self.__num_stream_loads = 0
    self.__num_stream_stores = 0
    self.__num_indirect_stream_loads = 0
    self.__num_indirect_stream_stores = 0
    self.__check_mem_ops(info)

  def __check_mss(self, info: Dict[str, Any]) -> None:
    # select all supported induction variable streams
    ivs = set()
    for iv in info['inductionVariableStreams']:
      final = iv['finalVal']
      if final is not None and final['invariant']:
        ivs.add(iv['name'])
    # select all supported memory streams
    mss = {}
    for ms in info['memStreams']:
      if ms['read'] or ms['written']:
        mss[ms['name']] = ms
    # use `list(mss.values())` because `__check_ms` may delete value from `mss`
    for ms in list(mss.values()):
      self.__check_ms(ivs, mss, ms)

  def __check_ms(self, ivs: Set[str], mss: Dict[str, Dict[str, Any]],
                 ms: Dict[str, Any]) -> bool:
    '''
    Checks the given memory stream.

    Returns `True` if the given stream is a supported stream.
    '''
    # check if visited
    name = ms['name']
    if name in self.__supported_mss:
      return True
    if name not in mss:
      return False
    # check all factors
    is_indirect = False
    for factor in ms['factors']:
      ret, ind = self.__check_addr_factor(ivs, mss, name, factor)
      if not ret:
        return False
      if ind:
        is_indirect = True
    # update result
    self.__supported_mss.add(name)
    if is_indirect:
      self.__indirect_supported_mss.add(name)
    num_iv_factors = 0
    num_ms_factors = 0
    for factor in ms['factors']:
      kind = factor['depStreamKind']
      if kind == 'inductionVariable':
        num_iv_factors += 1
        self.__supported_ivs.add(factor['depStream'])
      elif kind == 'memory':
        num_ms_factors += 1
    self.__max_num_iv_factors = max(self.__max_num_iv_factors, num_iv_factors)
    self.__max_num_ms_factors = max(self.__max_num_ms_factors, num_ms_factors)
    self.__max_width = max(self.__max_width, ms['width'])
    return True

  def __check_addr_factor(self, ivs: Set[str], mss: Dict[str, Dict[str, Any]],
                          name: str, factor: Dict[str, Any]) -> Tuple[bool, bool]:
    '''
    Checks the given address factor.
    
    Returns a tuple of the check result and whether the factor
    references a memory stream.
    '''
    def fail() -> Tuple[bool, bool]:
      del mss[name]
      return False, False

    invariant = factor['invariant']
    dep = factor['depStream']
    kind = factor['depStreamKind']
    # check dependent stream
    if kind == 'notAStream':
      if not invariant:
        # using a non-stream loop variant
        return fail()
    elif kind == 'inductionVariable':
      if dep not in ivs:
        # referencing an unsupported induction variable stream
        return fail()
    elif kind == 'memory':
      if dep not in mss or not self.__check_ms(ivs, mss, mss[dep]):
        # referencing an unsupported memory stream
        return fail()
      return True, True
    # check strides
    for stride in factor['strides']:
      # using a loop variant as stride
      if not stride['invariant']:
        return fail()
      # div can only be applied on constant value, otherwise may lost accuracy
      if stride['op'].endswith('div') and kind != 'notAStream':
        return fail()
    return True, False

  def __check_ivs(self, info: Dict[str, Any]) -> None:
    iv_parent = {}
    iv_chain_len = {}
    for iv in info['inductionVariableStreams']:
      name, parent = iv['name'], iv['parent']
      iv_parent[name] = parent
      if name not in self.__supported_ivs:
        continue
      # update induction variable chain info
      if parent is not None and parent not in self.__supported_ivs:
        while parent is not None and parent not in self.__supported_ivs:
          parent = iv_parent[parent]
        iv_parent[name] = parent
      if parent is None:
        chain_len = 1
      else:
        chain_len = iv_chain_len[parent] + 1
      iv_chain_len[name] = chain_len
      self.__max_iv_chain_len = max(self.__max_iv_chain_len, chain_len)

  def __check_mem_ops(self, info: Dict[str, Any]) -> None:
    for op in info['memOps']:
      supported = op['memStream'] in self.__supported_mss
      indirect = op['memStream'] in self.__indirect_supported_mss
      if op['memOpcode'] == 'load':
        self.__num_loads += 1
        self.__num_stream_loads += int(supported)
        self.__num_indirect_stream_loads += int(indirect)
      elif op['memOpcode'] == 'store':
        self.__num_stores += 1
        self.__num_stream_stores += int(supported)
        self.__num_indirect_stream_stores += int(indirect)

  @property
  def num_ivs(self) -> int:
    '''
    Returns the number of induction variable streams.
    '''
    return self.__num_ivs

  @property
  def num_supported_ivs(self) -> int:
    '''
    Returns the number of supported induction variable streams.
    '''
    return len(self.__supported_ivs)

  @property
  def max_iv_chain_len(self) -> int:
    '''
    Returns the maximum induction variable chain length.
    '''
    return self.__max_iv_chain_len

  @property
  def num_mss(self) -> int:
    '''
    Returns the number of memory streams.
    '''
    return self.__num_mss

  @property
  def num_supported_mss(self) -> int:
    '''
    Returns the number of supported memory streams.
    '''
    return len(self.__supported_mss)

  @property
  def num_indirect_supported_mss(self) -> int:
    '''
    Returns the number of indirect supported memory streams.
    '''
    return len(self.__indirect_supported_mss)

  @property
  def max_num_iv_factors(self) -> int:
    '''
    Returns the maximum number of induction variable stream factors.
    '''
    return self.__max_num_iv_factors

  @property
  def max_num_ms_factors(self) -> int:
    '''
    Returns the maximum number of memory stream factors.
    '''
    return self.__max_num_ms_factors

  @property
  def max_width(self) -> int:
    '''
    Returns the maximum width (in bytes) of memory streams.
    '''
    return self.__max_width

  @property
  def num_loads(self) -> int:
    '''
    Returns the number of load operations.
    '''
    return self.__num_loads

  @property
  def num_stream_loads(self) -> int:
    '''
    Returns the number of memory stream load operations.
    '''
    return self.__num_stream_loads

  @property
  def num_indirect_stream_loads(self) -> int:
    '''
    Returns the number of indirect memory stream load operations.
    '''
    return self.__num_indirect_stream_loads

  @property
  def num_stores(self) -> int:
    '''
    Returns the number of store operations.
    '''
    return self.__num_stores

  @property
  def num_stream_stores(self) -> int:
    '''
    Returns the number of memory stream store operations.
    '''
    return self.__num_stream_stores

  @property
  def num_indirect_stream_stores(self) -> int:
    '''
    Returns the number of indirect memory stream store operations.
    '''
    return self.__num_indirect_stream_stores

  def is_supported_iv(self, name: str) -> bool:
    '''
    Returns `True` if the given name corresponding to a supported
    induction variable stream.
    '''
    return name in self.__supported_ivs

  def is_indirect_supported_ms(self, name: str) -> bool:
    '''
    Returns `True` if the given name corresponding to a supported
    indirect memory stream.
    '''
    return name in self.__indirect_supported_mss


@dataclass(frozen=True)
class AnalysisResult:
  '''
  Analysis result of the given stream information list.
  '''

  num_loops: int
  num_partially_streamizable: int
  num_fully_streamizable: int
  max_width: int
  num_supported_mss: int
  num_indirect_supported_mss: int
  num_loads: int
  num_stream_loads: int
  num_indirect_stream_loads: int
  num_stores: int
  num_stream_stores: int
  num_indirect_stream_stores: int
  max_ivs_num_freq: Tuple[int, int] = (0, 0)
  most_freq_ivs: Tuple[int, int] = (0, 0)
  max_iv_chain_len_freq: Tuple[int, int] = (0, 0)
  most_freq_iv_chain_lens: Tuple[int, int] = (0, 0)
  max_mss_num_freq: Tuple[int, int] = (0, 0)
  most_freq_mss: Tuple[int, int] = (0, 0)
  max_iv_factors_num_freq: Tuple[int, int] = (0, 0)
  most_freq_iv_factors: Tuple[int, int] = (0, 0)
  max_ms_factors_num_freq: Tuple[int, int] = (0, 0)
  most_freq_ms_factors: Tuple[int, int] = (0, 0)

  def __init__(self, streams: List[StreamInfo]) -> None:
    num_loops = len(streams)
    num_partially_streamizable = 0
    num_fully_streamizable = 0
    num_ivs_freq_dist = {}
    num_iv_chain_len_freq_dist = {}
    num_mss_freq_dist = {}
    num_iv_factor_freq_dist = {}
    num_ms_factor_freq_dist = {}
    max_width = 0
    num_supported_mss = 0
    num_indirect_supported_mss = 0
    num_loads = 0
    num_stream_loads = 0
    num_indirect_stream_loads = 0
    num_stores = 0
    num_stream_stores = 0
    num_indirect_stream_stores = 0
    for stream in streams:
      # streamizable loops
      if stream.num_supported_mss:
        if stream.num_supported_mss == stream.num_mss:
          num_fully_streamizable += 1
        else:
          num_partially_streamizable += 1
      # streams frequency distribution
      prev = num_ivs_freq_dist.setdefault(stream.num_supported_ivs, 0)
      num_ivs_freq_dist[stream.num_supported_ivs] = prev + 1
      prev = num_iv_chain_len_freq_dist.setdefault(stream.max_iv_chain_len, 0)
      num_iv_chain_len_freq_dist[stream.max_iv_chain_len] = prev + 1
      prev = num_mss_freq_dist.setdefault(stream.num_supported_mss, 0)
      num_mss_freq_dist[stream.num_supported_mss] = prev + 1
      prev = num_iv_factor_freq_dist.setdefault(stream.max_num_iv_factors, 0)
      num_iv_factor_freq_dist[stream.max_num_iv_factors] = prev + 1
      prev = num_ms_factor_freq_dist.setdefault(stream.max_num_ms_factors, 0)
      num_ms_factor_freq_dist[stream.max_num_ms_factors] = prev + 1
      # width of memory streams
      max_width = max(max_width, stream.max_width)
      # indirect memory streams percentage
      num_supported_mss += stream.num_supported_mss
      num_indirect_supported_mss += stream.num_indirect_supported_mss
      # memory operations percentage
      num_loads += stream.num_loads
      num_stream_loads += stream.num_stream_loads
      num_indirect_stream_loads += stream.num_indirect_stream_loads
      num_stores += stream.num_stores
      num_stream_stores += stream.num_stream_stores
      num_indirect_stream_stores += stream.num_indirect_stream_stores
    # update result
    object.__setattr__(self, 'num_loops', num_loops)
    object.__setattr__(self, 'num_partially_streamizable',
                       num_partially_streamizable)
    object.__setattr__(self, 'num_fully_streamizable', num_fully_streamizable)
    if len(num_ivs_freq_dist):
      object.__setattr__(self, 'max_ivs_num_freq',
                         max(num_ivs_freq_dist.items(), key=lambda x: x[0]))
      num_ivs_freq_dist.pop(0, None)
    if len(num_ivs_freq_dist):
      object.__setattr__(self, 'most_freq_ivs',
                         max(num_ivs_freq_dist.items(), key=lambda x: x[1]))
    if len(num_iv_chain_len_freq_dist):
      object.__setattr__(self, 'max_iv_chain_len_freq',
                         max(num_iv_chain_len_freq_dist.items(), key=lambda x: x[0]))
      num_iv_chain_len_freq_dist.pop(0, None)
    if len(num_iv_chain_len_freq_dist):
      object.__setattr__(self, 'most_freq_iv_chain_lens',
                         max(num_iv_chain_len_freq_dist.items(), key=lambda x: x[1]))
    if len(num_mss_freq_dist):
      object.__setattr__(self, 'max_mss_num_freq',
                         max(num_mss_freq_dist.items(), key=lambda x: x[0]))
      num_mss_freq_dist.pop(0, None)
    if len(num_mss_freq_dist):
      object.__setattr__(self, 'most_freq_mss',
                         max(num_mss_freq_dist.items(), key=lambda x: x[1]))
    if len(num_iv_factor_freq_dist):
      object.__setattr__(self, 'max_iv_factors_num_freq',
                         max(num_iv_factor_freq_dist.items(), key=lambda x: x[0]))
      num_iv_factor_freq_dist.pop(0, None)
    if len(num_iv_factor_freq_dist):
      object.__setattr__(self, 'most_freq_iv_factors',
                         max(num_iv_factor_freq_dist.items(), key=lambda x: x[1]))
    if len(num_ms_factor_freq_dist):
      object.__setattr__(self, 'max_ms_factors_num_freq',
                         max(num_ms_factor_freq_dist.items(), key=lambda x: x[0]))
      num_ms_factor_freq_dist.pop(0, None)
    if len(num_ms_factor_freq_dist):
      object.__setattr__(self, 'most_freq_ms_factors',
                         max(num_ms_factor_freq_dist.items(), key=lambda x: x[1]))
    object.__setattr__(self, 'max_width', max_width)
    object.__setattr__(self, 'num_supported_mss', num_supported_mss)
    object.__setattr__(self, 'num_indirect_supported_mss',
                       num_indirect_supported_mss)
    object.__setattr__(self, 'num_loads', num_loads)
    object.__setattr__(self, 'num_stream_loads', num_stream_loads)
    object.__setattr__(self, 'num_indirect_stream_loads',
                       num_indirect_stream_loads)
    object.__setattr__(self, 'num_stores', num_stores)
    object.__setattr__(self, 'num_stream_stores', num_stream_stores)
    object.__setattr__(self, 'num_indirect_stream_stores',
                       num_indirect_stream_stores)

  def print(self, file: Optional[IO] = None, indent_width: int = 0) -> None:
    '''
    Prints the analysis result.
    '''
    def p(*args):
      print(*args, file=file)
    indent = ' ' * indent_width
    p(f'{indent}num loops: {self.num_loops}')
    if not self.num_loops:
      return
    p(f'{indent}partially streamizable loops:', self.num_partially_streamizable,
      f'({self.num_partially_streamizable / self.num_loops * 100:.2f}%)')
    p(f'{indent}fully streamizable loops:', self.num_fully_streamizable,
      f'({self.num_fully_streamizable / self.num_loops * 100:.2f}%)')
    all_streamizable = self.num_partially_streamizable + self.num_fully_streamizable
    p(f'{indent}streamizable loops:', all_streamizable,
      f'({all_streamizable / self.num_loops * 100:.2f}%)')
    p(f'{indent}max induction variable streams (num, freq):',
      self.max_ivs_num_freq)
    p(f'{indent}most freq induction variable streams (num, freq):',
      f'{self.most_freq_ivs}')
    p(f'{indent}max induction variable chain (length, freq):',
      self.max_iv_chain_len_freq)
    p(f'{indent}most freq induction variable chain (length, freq):',
      f'{self.most_freq_iv_chain_lens}')
    p(f'{indent}max memory streams (num, freq): {self.max_mss_num_freq}')
    p(f'{indent}most freq memory streams (num, freq): {self.most_freq_mss}')
    p(f'{indent}max induction variable stream factors (num, freq):',
      self.max_iv_factors_num_freq)
    p(f'{indent}most freq induction variable stream factors (num, freq):',
      self.most_freq_iv_factors)
    p(f'{indent}max memory stream factors (num, freq):',
      self.max_ms_factors_num_freq)
    p(f'{indent}most freq memory stream factors (num, freq):',
      self.most_freq_ms_factors)
    p(f'{indent}max width: {self.max_width}')
    p(f'{indent}supported memory streams: {self.num_supported_mss}')
    if self.num_supported_mss:
      p(f'{indent}indirect memory streams:', self.num_indirect_supported_mss,
        f'({self.num_indirect_supported_mss / self.num_supported_mss * 100:.2f}%)')
    p(f'{indent}total loads: {self.num_loads}')
    if self.num_loads:
      p(f'{indent}stream loads:', self.num_stream_loads,
        f'({self.num_stream_loads / self.num_loads * 100:.2f}%)')
      if self.num_stream_loads:
        p(f'{indent}indirect stream loads:', self.num_indirect_stream_loads,
          f'({self.num_indirect_stream_loads / self.num_stream_loads * 100:.2f}%)')
    p(f'{indent}total stores: {self.num_stores}')
    if self.num_stores:
      p(f'{indent}stream stores:', self.num_stream_stores,
        f'({self.num_stream_stores / self.num_stores * 100:.2f}%)')
      if self.num_stream_stores:
        p(f'{indent}indirect stream stores:', self.num_indirect_stream_stores,
          f'({self.num_indirect_stream_stores / self.num_stream_stores * 100:.2f}%)')


def dump_csv(f: IO, results: Dict[str, AnalysisResult]) -> None:
  '''
  Dumps the given results to CSV file.
  '''
  print('name', 'num loops', 'partially streamizable loops',
        'fully streamizable loops', 'streamizable loops',
        'max induction variable streams', 'max induction variable streams freq',
        'most freq induction variable streams',
        'most freq induction variable streams freq',
        'max induction variable chain length',
        'max induction variable chain length freq',
        'most freq induction variable chain length',
        'most freq induction variable chain freq', 'max memory streams',
        'max memory streams freq', 'most freq memory streams',
        'most freq memory streams freq', 'max induction variable stream factors',
        'max induction variable stream factors freq',
        'most freq induction variable stream factors',
        'most freq induction variable stream factors freq',
        'max memory stream factors', 'max memory stream factors freq',
        'most freq memory stream factors',
        'most freq memory stream factors freq', 'max width',
        'supported memory streams', 'indirect memory streams', 'total loads',
        'stream loads', 'indirect stream loads', 'total stores', 'stream stores',
        'indirect stream stores', sep=',', file=f)
  for name, result in results.items():
    print(name, result.num_loops, result.num_partially_streamizable,
          result.num_fully_streamizable,
          result.num_partially_streamizable + result.num_fully_streamizable,
          result.max_ivs_num_freq[0], result.max_ivs_num_freq[1],
          result.most_freq_ivs[0], result.most_freq_ivs[1],
          result.max_iv_chain_len_freq[0], result.max_iv_chain_len_freq[1],
          result.most_freq_iv_chain_lens[0], result.most_freq_iv_chain_lens[1],
          result.max_mss_num_freq[0], result.max_mss_num_freq[1],
          result.most_freq_mss[0], result.most_freq_mss[1],
          result.max_iv_factors_num_freq[0], result.max_iv_factors_num_freq[1],
          result.most_freq_iv_factors[0], result.most_freq_iv_factors[1],
          result.max_ms_factors_num_freq[0], result.max_ms_factors_num_freq[1],
          result.most_freq_ms_factors[0], result.most_freq_ms_factors[1],
          result.max_width, result.num_supported_mss,
          result.num_indirect_supported_mss, result.num_loads,
          result.num_stream_loads, result.num_indirect_stream_loads,
          result.num_stores, result.num_stream_stores,
          result.num_indirect_stream_stores, sep=',', file=f)


if __name__ == '__main__':
  import argparse
  import sys
  parser = argparse.ArgumentParser(
      description='Analysis for SMX analysis JSON-format output.')
  parser.add_argument('dir', type=str, help='directory contains JSONs')
  parser.add_argument('-p', '--print', default=False, action='store_true',
                      help='print human readable analysis result')
  parser.add_argument('-o', '--output', type=str, default=None,
                      help='specify the output file')

  args = parser.parse_args()
  if args.output is None:
    file = sys.stdout
  else:
    file = open(args.output, 'w')

  results = {}
  for d in sorted(os.listdir(args.dir)):
    path = os.path.join(args.dir, d)
    if d.endswith('.smx.json') and os.path.isfile(path):
      with open(path) as f:
        streams = list(map(StreamInfo, json.load(f)))
      result = AnalysisResult(streams)
      name = '.'.join(d.split('.')[:-2])
      if args.print:
        print(name, file=file)
        result.print(file=file, indent_width=2)
      else:
        results[name] = result

  if not args.print:
    dump_csv(file, results)
  file.close()
