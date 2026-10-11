# QE Convergence Helper

`qeconv.py` prepares, submits, and analyses Quantum ESPRESSO convergence calculations. It sweeps combinations of `ecutwfc`, `ecutrho`, and automatic K-point meshes, creating one calculation directory for each combination.

## Requirements

- Python 3.10 or newer
- A Quantum ESPRESSO installation accessible to the batch jobs
- `matplotlib` to create the PNG plot (CSV and YAML-compatible reports use the Python standard library)
- A supported batch scheduler for submission: PBS (`qsub`) or Slurm (`sbatch`)

Install matplotlib if needed:

```sh
python -m pip install matplotlib
```

## Input files

Run `qeconv.py` from a directory containing:

- One or more QE input files matching `*.in` (or a pattern supplied with `--inputs`)
- A pseudopotential directory (default: `pseudo/`)
- A batch script (default: `run_qe.sh`)

The QE input should contain `&CONTROL` and `&SYSTEM` namelists. The script sets `prefix` and `pseudo_dir` in `&CONTROL`, sets or adds `ecutwfc` and `ecutrho` in `&SYSTEM`, and replaces the `K_POINTS` card with an automatic mesh. Other input settings are retained. Each case receives a copy of the input file(s), the batch script, and the pseudopotential directory.

## Interactive workflow

Start the menu with:

```sh
python qeconv.py
```

Choose one of the three actions:

1. **Prepare**: enter input pattern, pseudo directory, run script, cutoff values or an `ecutrho` multiplier, and K-point meshes.
2. **Submit**: submit prepared cases using `qsub` for PBS scripts or `sbatch` for Slurm scripts.
3. **Analyse**: read completed QE output files and create a CSV, PNG plot, and analysis report.

The default convergence root is the current directory (`.`). The generated layout is:

```text
.
├── k4x4x4/
│   ├── conv_001_wfc30_rho120/
│   │   ├── run_qe.sh
│   │   ├── input.in
│   │   └── pseudo/
│   └── ...
├── prepare.yaml
├── submit.yaml
├── analyze.yaml
├── convergence.csv
└── convergence.png
```

The names and case numbers reflect the values supplied during preparation. The script updates common scheduler job-name directives (`#PBS -N`, `#SBATCH -J`, and `#SBATCH --job-name`). Keep the run script's QE input and output filenames consistent with the copied input file.

## Command-line examples

Prepare every combination of the listed cutoffs and meshes:

```sh
python qeconv.py prepare \
  --inputs '*.in' \
  --pseudo pseudo \
  --run-script run_qe.sh \
  --ecutwfc 30,40,50 \
  --ecutrho 120,160,200 \
  --kpoints 4x4x4,6x6x6,8x8x8 \
  --root .
```

This example creates the Cartesian product of the three `ecutwfc` values, three `ecutrho` values, and three meshes (27 cases). Alternatively, use a single `ecutrho` multiplier for each `ecutwfc` value:

```sh
python qeconv.py prepare --ecutwfc 30,40,50 --rho-ratio 4 --kpoints 4x4x4,6x6x6,8x8x8
```

Submit or analyse the cases later:

```sh
python qeconv.py submit --root .
python qeconv.py analyse --root .
```

Custom analysis output paths are available with `--csv` and `--png`:

```sh
python qeconv.py analyse --root . --csv results.csv --png results.png
```

Use `python qeconv.py --help` for all command-line options.

## Analysis outputs

- `convergence.csv` contains one row per prepared case, including its mesh, cutoffs, final parsed total energy, and status.
- `convergence.png` plots total energy in Ry against K-point mesh. Each cutoff pair is shown as a separate colored series.
- `analyze.yaml` lists analysed cases and output paths, plus a suggested tested setting. The suggestion uses the highest-tested-setting case as an energy reference and chooses the lowest estimated-cost case within `1e-4 Ry` of that energy. This tolerance is defined by `ENERGY_CONVERGENCE_TOLERANCE_RY` in the script; treat the suggestion as a screening heuristic and review it for the material and calculation settings.
- `prepare.yaml` records the matched source files, prepared case directories, cutoffs, and meshes.
- `submit.yaml` records scheduler, job ID (when returned by the scheduler), status, and response for each case.

QE total energies are read from output files ending in `.out` or `.log` using the standard `! total energy = ... Ry` line. The last matching energy in each case is used.
