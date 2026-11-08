"""Write SHA256SUMS for the frozen research_v4 inputs (questions, gold, definitions, oracle and validators).

Run after generate.py and before any paid model run; a later change to any listed file shows up in `git diff` of
SHA256SUMS and in the hashes the accuracy runner records. worlds/real.sha256 pins the large derived world separately.
"""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[2]
FILES = [ROOT / n for n in ("cases.yaml", "manifest.yaml", "GLOSSARY.md", "generate.py", "export_world.py", "AUDIT_A.csv", "AUDIT_B.csv")]
FILES += [PROJECT / "backend/eval" / n for n in ("oracle_csv.py", "validate_research_v4.py", "benchmark.py")]
lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(PROJECT)}" for p in FILES]
(ROOT / "SHA256SUMS").write_text("\n".join(lines) + "\n")
print("\n".join(lines))
