#!/usr/bin/env python3

from typing import Callable
import struct
import sys
import subprocess


RECORD_FMT = '@Pdd'
RECORD_LEN = struct.calcsize(RECORD_FMT)
unpack_record = struct.Struct(RECORD_FMT).unpack_from

RELOCATION_FMT = '@P'
RELOCATION_LEN = struct.calcsize(RELOCATION_FMT)
unpack_relocation = struct.Struct(RELOCATION_FMT).unpack_from


LocQuery = Callable[[int], str]


def print_record(i: int, rel: int, query: LocQuery, data: bytes) -> None:
  addr, read_mpki, write_mpki = unpack_record(data)
  rel_addr = addr - rel
  print(f'Loop #{i}:')
  print(f'  Address: {hex(rel_addr)}')
  print(f'  Location: {query(rel_addr)}')
  print(f'  Cache Read MPKI: {read_mpki:.4f}')
  print(f'  Cache Write MPKI: {write_mpki:.4f}')


if __name__ == '__main__':
  if len(sys.argv) != 3:
    print(f'usage: {sys.argv[0]} BINARY PROF_FILE')
    exit(1)

  bin = sys.argv[1]
  prof = sys.argv[2]

  # define the location query function
  def query(addr: int) -> str:
    ret = subprocess.run(['addr2line', '-e', bin, hex(addr)],
                         capture_output=True, text=True)
    return 'Unknown' if ret.returncode else ret.stdout.strip()

  # read the profile data
  with open(prof, 'rb') as f:
    # get relocation
    rel_data = f.read(RELOCATION_LEN)
    rel = unpack_relocation(rel_data)[0]
    print(hex(rel))
    # print records
    i = 0
    while data := f.read(RECORD_LEN):
      print_record(i, rel, query, data)
      i += 1
