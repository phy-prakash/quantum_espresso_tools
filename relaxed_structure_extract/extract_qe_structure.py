
#!/usr/bin/env python3
import re
import sys
from pathlib import Path


def extract_relaxed_structure(filename):
    text = Path(filename).read_text(errors="replace")

    # Extract the final CELL_PARAMETERS block
    cell_blocks = list(re.finditer(
        r"CELL_PARAMETERS\s*(?:\(([^)]*)\)|([^\n]*))\s*\n"
        r"((?:\s*[-+0-9.eEdD]+\s+[-+0-9.eEdD]+\s+[-+0-9.eEdD]+\s*\n){3})",
        text,
        re.IGNORECASE
    ))

    # Extract all ATOMIC_POSITIONS blocks
    pos_blocks = list(re.finditer(
        r"ATOMIC_POSITIONS\s*(?:\(([^)]*)\)|([^\n]*))\s*\n"
        r"((?:\s*[A-Za-z][A-Za-z0-9_]*\s+[-+0-9.eEdD]+\s+"
        r"[-+0-9.eEdD]+\s+[-+0-9.eEdD]+[^\n]*\n)+)",
        text,
        re.IGNORECASE
    ))

    if not pos_blocks:
        raise ValueError("No ATOMIC_POSITIONS block found in the output.")

    # The final atomic positions are normally the relaxed positions
    positions = pos_blocks[-1]
    pos_unit = (positions.group(1) or positions.group(2) or "").strip()
    atom_lines = positions.group(3).strip().splitlines()

    # The final cell is needed for variable-cell relaxation
    if cell_blocks:
        cell = cell_blocks[-1]
        cell_unit = (cell.group(1) or cell.group(2) or "").strip()
        cell_lines = cell.group(3).strip().splitlines()
    else:
        cell_unit = ""
        cell_lines = []

    output = []

    if cell_lines:
        output.append(
            "CELL_PARAMETERS" +
            (f" ({cell_unit})" if cell_unit else "")
        )
        output.extend(line.strip() for line in cell_lines)

    output.append(
        "ATOMIC_POSITIONS" +
        (f" ({pos_unit})" if pos_unit else "")
    )
    output.extend(line.strip() for line in atom_lines)

    out_file = Path(filename).with_suffix(".relaxed.in")
    out_file.write_text("\n".join(output) + "\n")

    print(f"Extracted structure saved to: {out_file}")
    print("\n" + "\n".join(output))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python extract_qe_structure.py calculation.out")
        sys.exit(1)

    extract_relaxed_structure(sys.argv[1])
