#!/usr/bin/env python3

from typing import Dict, Any, List
import json
import sys
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
    mss = {}
    for ms in info['memStreams']:
      if ms['read'] or ms['written']:
        mss[ms['name']] = ms
    for ms in list(mss.values()):
      self.__check_ms(mss, ms)

  def __check_ms(self, mss: Dict[str, Dict[str, Any]], ms: Dict[str, Any]) -> bool:
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
      if factor['depStreamKind'] == 'notAStream' and not factor['invariant']:
        # using a non-stream loop variant
        del mss[name]
        return False
      if factor['depStreamKind'] == 'memory':
        dep = factor['depStream']
        if dep not in mss or not self.__check_ms(mss, mss[dep]):
          # referencing an unsupported memory stream
          del mss[name]
          return False
        is_indirect = True
    # update result
    self.__supported_mss.add(name)
    if is_indirect:
      self.__indirect_supported_mss.add(name)
    for factor in ms['factors']:
      if factor['depStreamKind'] == 'inductionVariable':
        self.__supported_ivs.add(factor['depStream'])
    return True

  def __check_ivs(self, info: Dict[str, Any]) -> None:
    iv_parent = {}
    iv_chain_len = {}
    for iv in info['inductionVariableStreams']:
      name, parent = iv['name'], iv['parent']
      iv_parent[name] = parent
      if name not in self.__supported_ivs:
        continue
      if not iv['increasing']:
        self.__supported_ivs.remove(name)
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


@dataclass(frozen=True)
class AnalysisResult:
  '''
  Analysis result of the given stream information list.
  '''

  num_loops: int
  num_partially_streamizable: int
  num_fully_streamizable: int
  num_ivs_freq_dist: Dict[int, int]
  num_iv_chain_len_freq_dist: Dict[int, int]
  num_mss_freq_dist: Dict[int, int]
  num_supported_mss: int
  num_indirect_supported_mss: int
  num_loads: int
  num_stream_loads: int
  num_indirect_stream_loads: int
  num_stores: int
  num_stream_stores: int
  num_indirect_stream_stores: int

  def __init__(self, streams: List[StreamInfo]) -> None:
    num_loops = len(streams)
    num_partially_streamizable = 0
    num_fully_streamizable = 0
    num_ivs_freq_dist = {}
    num_iv_chain_len_freq_dist = {}
    num_mss_freq_dist = {}
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
    object.__setattr__(self, 'num_ivs_freq_dist', num_ivs_freq_dist)
    object.__setattr__(self, 'num_iv_chain_len_freq_dist',
                       num_iv_chain_len_freq_dist)
    object.__setattr__(self, 'num_mss_freq_dist', num_mss_freq_dist)
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

  def print(self, indent_width: int = 0) -> None:
    '''
    Prints the analysis result.
    '''
    indent = ' ' * indent_width
    print(f'{indent}num loops: {self.num_loops}')
    if not self.num_loops:
      return
    print(f'{indent}partially streamizable loops:', self.num_partially_streamizable,
          f'({self.num_partially_streamizable / self.num_loops * 100:.2f}%)')
    print(f'{indent}fully streamizable loops:', self.num_fully_streamizable,
          f'({self.num_fully_streamizable / self.num_loops * 100:.2f}%)')
    all_streamizable = self.num_partially_streamizable + self.num_fully_streamizable
    print(f'{indent}streamizable loops:', all_streamizable,
          f'({all_streamizable / self.num_loops * 100:.2f}%)')
    print(f'{indent}max induction variable streams:',
          max(self.num_ivs_freq_dist.keys()))
    self.num_ivs_freq_dist.pop(0, None)
    print(f'{indent}most freq. induction variable streams (num, freq):',
          f'{max(self.num_ivs_freq_dist.items(), key=lambda x: x[1])}')
    print(f'{indent}max induction variable chain length:',
          max(self.num_iv_chain_len_freq_dist.keys()))
    self.num_iv_chain_len_freq_dist.pop(0, None)
    print(f'{indent}most freq. induction variable chain (length, freq):',
          f'{max(self.num_iv_chain_len_freq_dist.items(), key=lambda x: x[1])}')
    print(f'{indent}max memory streams: {max(self.num_mss_freq_dist.keys())}')
    self.num_mss_freq_dist.pop(0, None)
    print(f'{indent}most freq. memory streams (num, freq):',
          f'{max(self.num_mss_freq_dist.items(), key=lambda x: x[1])}')
    print(f'{indent}supported memory streams: {self.num_supported_mss}')
    if self.num_supported_mss:
      print(f'{indent}indirect memory streams:', self.num_indirect_supported_mss,
            f'({self.num_indirect_supported_mss / self.num_supported_mss * 100:.2f}%)')
    print(f'{indent}total loads: {self.num_loads}')
    if self.num_loads:
      print(f'{indent}stream loads:', self.num_stream_loads,
            f'({self.num_stream_loads / self.num_loads * 100:.2f}%)')
      if self.num_stream_loads:
        print(f'{indent}indirect stream loads:', self.num_indirect_stream_loads,
              f'({self.num_indirect_stream_loads / self.num_stream_loads * 100:.2f}%)')
    print(f'{indent}total stores: {self.num_stores}')
    if self.num_stores:
      print(f'{indent}stream stores:', self.num_stream_stores,
            f'({self.num_stream_stores / self.num_stores * 100:.2f}%)')
      if self.num_stream_stores:
        print(f'{indent}indirect stream stores:', self.num_indirect_stream_stores,
              f'({self.num_indirect_stream_stores / self.num_stream_stores * 100:.2f}%)')


if __name__ == '__main__':
  if len(sys.argv) < 2:
    print(f'usage: {sys.argv[0]} DIRECTORY')
    exit(1)

  dir = sys.argv[1]
  for d in sorted(os.listdir(dir)):
    path = os.path.join(dir, d)
    (name, ext) = os.path.splitext(d)
    if ext == '.json' and os.path.isfile(path):
      with open(path) as f:
        streams = list(map(StreamInfo, json.load(f)))
      print(d)
      AnalysisResult(streams).print(2)
