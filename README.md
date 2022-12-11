# SMX Related Utilities

This repository contains many useful utilities for the RISC-V stream-based memory access extension.

## Usage of Utilities

### [smx_analysis.py](smx_analysis.py)

Run SMX analysis on projects/repositories, such as SPEC CPU, by the given compilation configurations.

Example:

```
mkdir spec06
./smx_analysis.py /path/to/spec06/src \
  -c config.spec06.json \
  -l /path/to/smx-transforms/src/libSMXTransforms.so \
  -o spec06
```

Then analysis results will be stored in `spec06/benchmark_name.json`.

### [result_analysis.py](result_analysis.py)

Analyse the analysis results collected by `smx_analysis.py`.

Example:

```
./result_analysis.py spec06
```

## License

[GPL-v3](LICENSE).
