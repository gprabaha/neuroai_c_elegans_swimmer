import os
from pathlib import Path
from textwrap import dedent

# === Constants ===
SRC = Path("src")
RUNNERS = SRC / "runners"
MAIN_PY = SRC / "main.py"
RUNNER_PY = SRC / "runner.py"
TRAIN_SH = Path("train.sh")

# === Boilerplate Code ===
main_py_code = dedent("""\
    import argparse
    from src.runner import run_training

    def main():
        parser = argparse.ArgumentParser()
        parser.add_argument("--config", type=str, default="configs/swimmer_ppo.yaml")
        args = parser.parse_args()
        run_training(args.config)

    if __name__ == "__main__":
        main()
""")

runner_py_code = dedent("""\
    import yaml

    def run_training(config_path):
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        print(f"Running training with config: {config}")
        # TODO: Add training logic here
""")

train_sh_code = dedent("""\
    #!/bin/bash
    python3 src/main.py --config configs/swimmer_ppo.yaml
""")

# === Actions ===

def ensure_init_files(path: Path):
    for subdir in path.glob("**/"):
        init_file = subdir / "__init__.py"
        if subdir.is_dir() and not init_file.exists():
            init_file.write_text("")

def write_file_if_missing(path: Path, content: str):
    if not path.exists():
        path.write_text(content)
        print(f"✔ Created: {path}")
    else:
        print(f"⏩ Skipped (already exists): {path}")

def move_runner_if_exists():
    old_runner = RUNNERS / "train_swimmer.py"
    if old_runner.exists():
        backup_path = SRC / "train_swimmer_backup.py"
        old_runner.rename(backup_path)
        print(f"🚚 Moved runner to: {backup_path}")

# === Execute ===

print("🔧 Setting up your project structure...\n")

# Create necessary __init__.py files
ensure_init_files(SRC)

# Write main.py and runner.py
write_file_if_missing(MAIN_PY, main_py_code)
write_file_if_missing(RUNNER_PY, runner_py_code)

# Create train.sh
write_file_if_missing(TRAIN_SH, train_sh_code)
TRAIN_SH.chmod(0o755)

# Move old runner
move_runner_if_exists()

print("\n✅ Setup complete!")
