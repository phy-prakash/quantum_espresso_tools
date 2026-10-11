#!/usr/bin/env python3
"""Prepare, submit, and analyse Quantum ESPRESSO convergence runs.

Run ``python qeconv.py`` for the interactive menu, or see ``--help``.
The prepare mode makes the Cartesian product of ecutwfc/ecutrho pairs and
K_POINTS automatic meshes, with one directory per calculation.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import itertools
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default if default is not None else "")


def int_list(value: str, label: str) -> list[int]:
    try:
        values = [int(x.strip()) for x in value.split(",") if x.strip()]
    except ValueError as exc:
        raise ValueError(f"{label} must be comma-separated integers") from exc
    if not values or any(x <= 0 for x in values):
        raise ValueError(f"{label} must contain positive integers")
    return values


def mesh_list(value: str) -> list[tuple[int, int, int]]:
    result = []
    for item in value.split(","):
        values = tuple(int(x.strip()) for x in item.lower().replace("x", " ").split())
        if len(values) != 3 or any(x <= 0 for x in values):
            raise ValueError("K-point meshes must look like 4x4x4,5x5x5")
        result.append(values)
    if not result:
        raise ValueError("At least one K-point mesh is required")
    return result


def update_input(text: str, ecutwfc: int, ecutrho: int, mesh: tuple[int, int, int],
                 job_name: str) -> str:
    """Set convergence values without changing unrelated QE input lines."""
    lines = text.splitlines()

    def set_namelist(section_name: str, key: str, value: str) -> None:
        start = next((i for i, line in enumerate(lines)
                      if re.match(rf"^\s*&{section_name}\b", line, re.I)), None)
        if start is None:
            raise ValueError(f"Input has no &{section_name.upper()} namelist")
        end = next((i for i in range(start + 1, len(lines))
                    if re.match(r"^\s*/\s*(?:!.*)?$", lines[i])), None)
        if end is None:
            raise ValueError(f"&{section_name.upper()} namelist has no closing slash")
        assignment = re.compile(rf"^(\s*{re.escape(key)}\s*=).*$", re.I)
        for i in range(start + 1, end):
            match = assignment.match(lines[i])
            if match:
                # Keep a trailing comment, while replacing only this assignment line.
                comment = ""
                if "!" in lines[i]:
                    comment = " " + lines[i][lines[i].index("!"):]
                lines[i] = f"{match.group(1)} {value},{comment}"
                return
        lines.insert(end, f"  {key} = {value},")

    set_namelist("CONTROL", "prefix", f"'{job_name}'")
    set_namelist("CONTROL", "pseudo_dir", "'./pseudo/'")
    set_namelist("SYSTEM", "ecutwfc", str(ecutwfc))
    set_namelist("SYSTEM", "ecutrho", str(ecutrho))

    # Keep the first K_POINTS card in place, replace its automatic mesh, and
    # remove any extra K_POINTS cards so QE receives exactly one definition.
    indices = [i for i, line in enumerate(lines)
               if re.match(r"^\s*K_POINTS\b", line, re.I)]
    mesh_line = f"{mesh[0]} {mesh[1]} {mesh[2]} 0 0 0"
    if indices:
        first = indices[0]
        lines[first] = "K_POINTS automatic"
        if first + 1 < len(lines):
            lines[first + 1] = mesh_line
        else:
            lines.append(mesh_line)
        # Remove duplicate cards and their one-line automatic payloads.
        for duplicate in reversed(indices[1:]):
            del lines[duplicate:min(duplicate + 2, len(lines))]
    else:
        lines.extend(["", "K_POINTS automatic", mesh_line])
    return "\n".join(lines) + "\n"


def update_run_script(text: str, job_name: str) -> str:
    # Common Slurm, PBS, and SGE job-name directives.
    patterns = [
        (r"(?im)^(\s*#SBATCH\s+-J\s+).+$", rf"\g<1>{job_name}"),
        (r"(?im)^(\s*#SBATCH\s+--job-name=).+$", rf"\g<1>{job_name}"),
        (r"(?im)^(\s*#PBS\s+-N\s+).+$", rf"\g<1>{job_name}"),
        (r"(?im)^(\s*#$\s+-N\s+).+$", rf"\g<1>{job_name}"),
    ]
    for pattern, repl in patterns:
        text = re.sub(pattern, repl, text)
    return text


def write_yaml(path: Path, data: dict) -> None:
    """Write a readable JSON document, which is also valid YAML 1.2."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def report_time() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def prepare(input_glob: str, pseudo_dir: Path, run_script: Path, output: Path,
            cutoffs: list[tuple[int, int]], meshes: list[tuple[int, int, int]]) -> int:
    inputs = sorted(Path.cwd().glob(input_glob))
    if not inputs:
        raise FileNotFoundError(f"No QE input files match {input_glob!r} in {Path.cwd()}")
    if not pseudo_dir.is_dir():
        raise FileNotFoundError(f"Pseudopotential directory not found: {pseudo_dir}")
    if not run_script.is_file():
        raise FileNotFoundError(f"Run script not found: {run_script}")
    output.mkdir(parents=True, exist_ok=True)
    cases = list(itertools.product(meshes, cutoffs))
    prepared = []
    for index, (mesh, (wfc, rho)) in enumerate(cases, start=1):
        mesh_name = f"k{mesh[0]}x{mesh[1]}x{mesh[2]}"
        label = f"conv_{index:03d}_wfc{wfc}_rho{rho}"
        folder = output / mesh_name / label
        folder.mkdir(parents=True, exist_ok=True)
        for source in inputs:
            updated = update_input(source.read_text(encoding="utf-8", errors="replace"), wfc, rho, mesh, label)
            (folder / source.name).write_text(updated, encoding="utf-8")
        shutil.copytree(pseudo_dir, folder / "pseudo", dirs_exist_ok=True)
        script_text = update_run_script(run_script.read_text(encoding="utf-8", errors="replace"), label)
        (folder / run_script.name).write_text(script_text, encoding="utf-8", newline="\n")
        prepared.append({
            "directory": str(folder.resolve()),
            "job_name": label,
            "ecutwfc_Ry": wfc,
            "ecutrho_Ry": rho,
            "kpoints": list(mesh),
            "input_files": [str((folder / source.name).resolve()) for source in inputs],
            "run_script": str((folder / run_script.name).resolve()),
            "pseudo_directory": str((folder / "pseudo").resolve()),
        })
    report = {
        "action": "prepare",
        "created_at_utc": report_time(),
        "status": "complete",
        "source_directory": str(Path.cwd().resolve()),
        "input_pattern": input_glob,
        "input_files_found": [str(p.resolve()) for p in inputs],
        "pseudo_source": str(pseudo_dir.resolve()),
        "pseudo_files_found": [str(p.relative_to(pseudo_dir)) for p in sorted(pseudo_dir.rglob("*")) if p.is_file()],
        "run_script_source": str(run_script.resolve()),
        "convergence_root": str(output.resolve()),
        "case_count": len(prepared),
        "cases": prepared,
    }
    report_path = output / "prepare.yaml"
    write_yaml(report_path, report)
    print(f"Wrote {report_path.resolve()}")
    print(f"Prepared {len(cases)} cases in {output.resolve()}")
    return len(cases)


def submit(root: Path) -> None:
    folders = sorted(p for p in root.glob("k*/conv_*") if p.is_dir())
    if not folders:
        raise FileNotFoundError(f"No conv_* case directories found in {root}")
    jobs = []
    for folder in folders:
        scripts = list(folder.glob("*.sh"))
        if not scripts:
            print(f"SKIP {folder.name}: no .sh script")
            jobs.append({"directory": str(folder.resolve()), "status": "skipped", "reason": "no .sh script"})
            continue
        script = scripts[0]
        content = script.read_text(encoding="utf-8", errors="replace")
        is_pbs = bool(re.search(r"(?im)^\s*#PBS\b", content))
        is_slurm = bool(re.search(r"(?im)^\s*#SBATCH\b", content))
        if is_pbs and is_slurm:
            detail = "run script contains both PBS and Slurm directives"
            print(f"FAILED {folder.name}: {detail}")
            jobs.append({"directory": str(folder.resolve()), "script": str(script.resolve()),
                         "status": "failed", "reason": detail})
            continue
        if is_pbs and shutil.which("qsub"):
            command = ["qsub", script.name]
        elif is_slurm and shutil.which("sbatch"):
            command = ["sbatch", script.name]
        elif is_pbs:
            detail = "qsub is not available"
            print(f"FAILED {folder.name}: {detail}")
            jobs.append({"directory": str(folder.resolve()), "scheduler": "PBS", "script": str(script.resolve()),
                         "status": "failed", "reason": detail})
            continue
        elif is_slurm:
            detail = "sbatch is not available"
            print(f"FAILED {folder.name}: {detail}")
            jobs.append({"directory": str(folder.resolve()), "scheduler": "Slurm", "script": str(script.resolve()),
                         "status": "failed", "reason": detail})
            continue
        elif shutil.which("sbatch"):
            command = ["sbatch", script.name]
        elif shutil.which("qsub"):
            command = ["qsub", script.name]
        else:
            detail = "no supported scheduler found (sbatch or qsub)"
            print(f"FAILED {folder.name}: {detail}")
            jobs.append({"directory": str(folder.resolve()), "script": str(script.resolve()),
                         "status": "failed", "reason": detail})
            continue
        result = subprocess.run(command, cwd=folder, text=True, capture_output=True)
        response = (result.stdout or result.stderr).strip()
        scheduler = "PBS" if command[0] == "qsub" else "Slurm"
        if result.returncode == 0:
            job_id_match = (re.search(r"\bSubmitted\s+batch\s+job\s+(\S+)", response, re.I)
                            if scheduler == "Slurm" else re.search(r"^\s*(\S+)", response))
            job_id = job_id_match.group(1) if job_id_match else None
            status = "submitted"
        else:
            job_id = None
            status = "failed"
        print(f"{'OK' if status == 'submitted' else 'FAILED'} {folder.name}: {response}")
        jobs.append({"directory": str(folder.resolve()), "scheduler": scheduler,
                     "script": str(script.resolve()), "job_id": job_id, "status": status,
                     "response": response, "return_code": result.returncode})
    submitted = sum(job["status"] == "submitted" for job in jobs)
    report = {"action": "submit", "created_at_utc": report_time(),
              "status": "complete" if submitted == len(jobs) else "partial",
              "convergence_root": str(root.resolve()), "job_count": len(jobs),
              "submitted_count": submitted, "jobs": jobs}
    report_path = root / "submit.yaml"
    write_yaml(report_path, report)
    print(f"Wrote {report_path.resolve()}")


ENERGY_RE = re.compile(r"!\s+total energy\s*=\s*([-+0-9.Ee]+)\s*Ry", re.I)
CASE_RE = re.compile(r"wfc(\d+)_rho(\d+)")
MESH_RE = re.compile(r"k(\d+)x(\d+)x(\d+)")
ENERGY_CONVERGENCE_TOLERANCE_RY = 1.0e-4


def analyse(root: Path, csv_path: Path | None = None, png_path: Path | None = None) -> None:
    rows = []
    for folder in sorted(p for p in root.glob("k*/conv_*") if p.is_dir()):
        match = CASE_RE.search(folder.name)
        mesh_match = MESH_RE.fullmatch(folder.parent.name)
        if not match or not mesh_match:
            continue
        wfc, rho = map(int, match.groups())
        k1, k2, k3 = map(int, mesh_match.groups())
        energy = None
        for output in sorted(folder.rglob("*")):
            if output.is_file() and output.suffix.lower() in {".out", ".log"}:
                found = ENERGY_RE.findall(output.read_text(encoding="utf-8", errors="replace"))
                if found:
                    energy = float(found[-1])
        rows.append({"folder": f"{folder.parent.name}/{folder.name}", "ecutwfc_Ry": wfc, "ecutrho_Ry": rho,
                     "k1": k1, "k2": k2, "k3": k3, "kpoints": f"{k1}x{k2}x{k3}",
                     "total_energy_Ry": energy, "status": "complete" if energy is not None else "missing energy"})
    if not rows:
        raise FileNotFoundError(f"No prepared convergence cases found in {root}")
    csv_path = csv_path or root / "convergence.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {csv_path.resolve()}")
    png_path = png_path or root / "convergence.png"
    plot_error = None
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        plot_error = "matplotlib is required for PNG plots"
    valid = [r for r in rows if r["total_energy_Ry"] is not None]
    if plot_error is None and not valid:
        plot_error = "No energies found; CSV was written but no plot can be made"
    if plot_error is None:
        meshes = sorted({(r["k1"], r["k2"], r["k3"]) for r in valid})
        x_positions = {mesh: i for i, mesh in enumerate(meshes)}
        cutoff_pairs = sorted({(r["ecutwfc_Ry"], r["ecutrho_Ry"]) for r in valid})
        colors = plt.get_cmap("viridis")
        fig, ax = plt.subplots(figsize=(10, 6))
        for color_index, (wfc, rho) in enumerate(cutoff_pairs):
            values = [r for r in valid if r["ecutwfc_Ry"] == wfc and r["ecutrho_Ry"] == rho]
            values.sort(key=lambda r: (r["k1"], r["k2"], r["k3"]))
            color = colors(color_index / max(1, len(cutoff_pairs) - 1))
            ax.plot([x_positions[(r["k1"], r["k2"], r["k3"])] for r in values],
                    [r["total_energy_Ry"] for r in values], marker="o", color=color,
                    label=f"ecutwfc={wfc} Ry, ecutrho={rho} Ry")
        ax.set_xticks(range(len(meshes)), [f"{a}x{b}x{c}" for a, b, c in meshes])
        ax.set(xlabel="K-point", ylabel="Total energy (Ry)", title="Quantum ESPRESSO convergence")
        ax.grid(True, alpha=0.3)
        ax.legend(title="Energy cutoff", bbox_to_anchor=(1.02, 1), loc="upper left")
        fig.tight_layout()
        fig.savefig(png_path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        print(f"Wrote {png_path.resolve()}")
    # Recommend the least expensive tested case within a fixed energy window
    # of the lowest-energy completed case. Record the criterion in the report.
    best_candidate = None
    reference_case = None
    if valid:
        max_wfc = max(r["ecutwfc_Ry"] for r in valid)
        max_rho = max(r["ecutrho_Ry"] for r in valid)
        max_mesh = max(((r["k1"], r["k2"], r["k3"]) for r in valid),
                       key=lambda mesh: (mesh[0] * mesh[1] * mesh[2], mesh))
        reference_rows = [r for r in valid if r["ecutwfc_Ry"] == max_wfc
                          and r["ecutrho_Ry"] == max_rho
                          and (r["k1"], r["k2"], r["k3"]) == max_mesh]
        reference_case = reference_rows[0] if reference_rows else max(
            valid, key=lambda r: (r["k1"] * r["k2"] * r["k3"] * r["ecutwfc_Ry"] * r["ecutrho_Ry"])
        )
        reference = reference_case["total_energy_Ry"]
        converged_candidates = [
            r for r in valid
            if abs(r["total_energy_Ry"] - reference) <= ENERGY_CONVERGENCE_TOLERANCE_RY
        ]
        best_candidate = min(
            converged_candidates,
            key=lambda r: (r["k1"] * r["k2"] * r["k3"] * r["ecutwfc_Ry"] * r["ecutrho_Ry"],
                           r["k1"], r["k2"], r["k3"], r["ecutwfc_Ry"], r["ecutrho_Ry"]),
        )
        best_candidate = {
            "kpoint": best_candidate["kpoints"],
            "ecutrho_Ry": best_candidate["ecutrho_Ry"],
            "ecutwfc_Ry": best_candidate["ecutwfc_Ry"],
            "total_energy_Ry": best_candidate["total_energy_Ry"],
            "case_directory": best_candidate["folder"],
        }
    report = {"action": "analyse", "created_at_utc": report_time(),
              "status": "complete" if plot_error is None else "partial",
              "convergence_root": str(root.resolve()),
              "directories_analysed": [r["folder"] for r in rows],
              "case_count": len(rows), "energy_found_count": len(valid),
              "csv_file": str(csv_path.resolve()),
              "png_file": str(png_path.resolve()) if plot_error is None else None,
              "plot_error": plot_error,
              "suggestion_method": {
                  "criterion": "energy within tolerance of the highest-tested-setting reference case",
                  "energy_tolerance_Ry": ENERGY_CONVERGENCE_TOLERANCE_RY,
                  "selection": "lowest estimated computational cost among qualifying tested cases",
                  "reference_case": reference_case["folder"] if reference_case else None,
                  "reference_energy_Ry": reference_case["total_energy_Ry"] if reference_case else None,
              },
              "suggested_best_converged_values": best_candidate,
              "cases": rows}
    report_path = root / "analyze.yaml"
    write_yaml(report_path, report)
    print(f"Wrote {report_path.resolve()}")


def interactive() -> None:
    print("Quantum ESPRESSO convergence workflow\n  1. prepare\n  2. submit\n  3. analyse")
    choice = ask("Choose action (1/2/3)")
    root = Path(ask("Convergence root directory", "."))
    if choice in {"1", "prepare"}:
        pattern = ask("QE input file pattern", "*.in")
        pseudo = Path(ask("Pseudopotential directory", "pseudo"))
        run_script = Path(ask("QE run script", "run_qe.sh"))
        wfc_values = int_list(ask("ecutwfc values in Ry (comma-separated)", "30,40,50,60"), "ecutwfc")
        rho_mode = ask("Enter ecutrho values, or a multiplier of ecutwfc", "4")
        if "," in rho_mode:
            rho_values = int_list(rho_mode, "ecutrho")
            cutoffs = list(itertools.product(wfc_values, rho_values))
        else:
            ratio = float(rho_mode)
            if ratio <= 0:
                raise ValueError("ecutrho multiplier must be positive")
            cutoffs = [(wfc, round(wfc * ratio)) for wfc in wfc_values]
        meshes = mesh_list(ask("K-point meshes (comma-separated, e.g. 4x4x4,6x6x6)", "4x4x4,6x6x6,8x8x8"))
        prepare(pattern, pseudo, run_script, root, cutoffs, meshes)
    elif choice in {"2", "submit"}:
        submit(root)
    elif choice in {"3", "analyse", "analyze"}:
        analyse(root)
    else:
        raise ValueError("Choose 1, 2, or 3")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=["prepare", "submit", "analyse", "analyze"])
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--inputs", default="*.in")
    parser.add_argument("--pseudo", type=Path, default=Path("pseudo"))
    parser.add_argument("--run-script", type=Path, default=Path("run_qe.sh"))
    parser.add_argument("--ecutwfc", help="comma-separated values in Ry")
    parser.add_argument("--ecutrho", help="comma-separated values in Ry (paired by position)")
    parser.add_argument("--rho-ratio", type=float, help="set ecutrho = ecutwfc * ratio")
    parser.add_argument("--kpoints", help="comma-separated meshes, e.g. 4x4x4,6x6x6")
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--png", type=Path)
    args = parser.parse_args()
    try:
        if not args.mode:
            interactive()
        elif args.mode == "prepare":
            if not args.ecutwfc or not args.kpoints or (not args.ecutrho and args.rho_ratio is None):
                parser.error("prepare requires --ecutwfc, --kpoints, and either --ecutrho or --rho-ratio")
            wfcs = int_list(args.ecutwfc, "ecutwfc")
            if args.ecutrho:
                rhos = int_list(args.ecutrho, "ecutrho")
                cutoffs = list(itertools.product(wfcs, rhos))
            else:
                if args.rho_ratio <= 0:
                    parser.error("--rho-ratio must be positive")
                cutoffs = [(w, round(w * args.rho_ratio)) for w in wfcs]
            prepare(args.inputs, args.pseudo, args.run_script, args.root, cutoffs, mesh_list(args.kpoints))
        elif args.mode == "submit":
            submit(args.root)
        else:
            analyse(args.root, args.csv, args.png)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
