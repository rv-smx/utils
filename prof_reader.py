#!/usr/bin/env python3

from typing import Callable, Dict, Any, Tuple
import struct
import sys
import subprocess
import json


RECORD_FMT = '@PdddQ'
RECORD_LEN = struct.calcsize(RECORD_FMT)
unpack_record = struct.Struct(RECORD_FMT).unpack_from

RELOCATION_FMT = '@P'
RELOCATION_LEN = struct.calcsize(RELOCATION_FMT)
unpack_relocation = struct.Struct(RELOCATION_FMT).unpack_from


LocQuery = Callable[[int], Tuple[str, str]]
Record = Dict[str, Any]


def get_record(rel: int, query: LocQuery, data: bytes) -> Record:
  addr, read_mpki, write_mpki, avg_insts, num_exec = unpack_record(data)
  rel_addr = addr - rel
  func, loc = query(rel_addr)
  return {
      'address': hex(rel_addr),
      'location': loc,
      'function': func,
      'readMpki': read_mpki,
      'writeMpki': write_mpki,
      'averageInstructions': avg_insts,
      'numExecutions': num_exec,
  }


def print_record(i: int, record: Record) -> None:
  print(f'Loop #{i}:')
  print(f'  Address: {record["address"]}')
  print(f'  Location: {record["location"]}')
  print(f'  Function: {record["function"]}')
  print(f'  Cache Read MPKI: {record["readMpki"]:.4f}')
  print(f'  Cache Write MPKI: {record["writeMpki"]:.4f}')
  print(f'  Average Instructions: {record["averageInstructions"]:.4f}')
  print(f'  Number of Executions: {record["numExecutions"]}')


if __name__ == '__main__':
  import argparse
  parser = argparse.ArgumentParser(description='Loop profile reader.')
  parser.add_argument('binary', type=str, help='binary file with debug info')
  parser.add_argument('profile', type=str, help='loop profile')
  parser.add_argument('-j', '--json', default=False, action='store_true',
                      help='dump JSON')
  parser.add_argument('-s', '--symbolizer', type=str, default=None,
                      help='specify the path to `llvm-symbolizer` executable')
  args = parser.parse_args()

  # define the location query function
  if args.symbolizer is None:
    symbolizer = 'llvm-symbolizer'
  else:
    symbolizer = args.symbolizer

  def query(addr: int) -> Tuple[str, str]:
    ret = subprocess.run([symbolizer, '-e', args.binary, '-f', '-s',
                          '--no-demangle', '--output-style=JSON', hex(addr - 1)],
                         capture_output=True, text=True)
    if ret.returncode:
      return '<Unknown>', '<Unknown>'
    sym = json.loads(ret.stdout)[0]['Symbol'][0]
    func = sym['FunctionName']
    loc = f'{sym["FileName"]}:{sym["Line"]}:{sym["Column"]}'
    return func, loc

  # read the profile data
  records = []
  with open(args.profile, 'rb') as f:
    # get relocation
    rel_data = f.read(RELOCATION_LEN)
    rel = unpack_relocation(rel_data)[0]
    # print records
    i = 0
    while data := f.read(RECORD_LEN):
      record = get_record(rel, query, data)
      if args.json:
        records.append(record)
      else:
        print_record(i, record)
      i += 1

  # dump JSON
  if args.json:
    json.dump(records, sys.stdout)
