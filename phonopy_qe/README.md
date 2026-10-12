# QE Phonopy pre-processing tool

## Phonopy force calculations

`phonopy_qe.py` prepares QE inputs from phonopy's `supercell-NNN.in` files.
Run it in the directory containing those files, `pseudo/`, and `run_qe.sh`:

```sh
python phonopy_qe.py prepare --unitcell pbte_ppy.in
python phonopy_qe.py submit
```

The prepare command asks for the unit-cell input filename if `--unitcell` is
omitted. It writes each merged QE input and a copy of the pseudopotentials and
batch script under `disp-run/NNN/`, updating `nat`, the structure cards, and
the batch job name. Each `pw.x` command reads `supercell-NNN.in` and redirects
to `supercell-NNN.out`. `prepare.yaml` records the generated cases. The submit
command uses `sbatch` or `qsub` based on the directives in each batch script
(`PBS_NODEFILE` also identifies a PBS script) and records responses and job IDs in `submit.yaml`. The interactive menu is
available with `python phonopy_qe.py`.
