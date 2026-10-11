
# QE Relaxed Structure Extractor

A simple Python script to extract the final relaxed crystal structure from Quantum ESPRESSO (`pw.x`) output files.

## Features

- Extracts the final `CELL_PARAMETERS` block, if available.
- Extracts the final `ATOMIC_POSITIONS` block.
- Supports `relax` and `vc-relax` output files.
- Preserves the units specified in the output.
- Saves the extracted structure to a separate file.
- Uses only Python standard libraries.

## Requirements

- Python 3.7 or later
- Quantum ESPRESSO output file (`.out`)

No external Python packages are required.

## Usage

Run the script using:

```bash
python extract_qe_structure.py pw.out
```

Replace `pw.out` with the name of your Quantum ESPRESSO output file.

## Output

The script generates a new file named:

```text
pw.relaxed.in
```

The output file contains the extracted `CELL_PARAMETERS` and `ATOMIC_POSITIONS` blocks when available.

## Important Notes

- For `vc-relax` calculations, verify that the final cell parameters and atomic positions correspond to the last completed relaxation step.
- For fixed-cell `relax` calculations, the original cell parameters may need to be retained if they are not present in the output file.
- The extracted file contains structural information only; it is not a complete Quantum ESPRESSO input file.
- Always verify the extracted structure before using it in subsequent calculations.

## License

MIT License (see `LICENSE` for details).

## Author
Prakash G
