import argparse
import os
import sys

# 确保能 import src 模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.workflows.profile_compiler import compile_strategy_profile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", type=str, default="")
    parser.add_argument("--profile", type=str, default="configs/strategy_profile.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        compile_strategy_profile(
            market=args.market, profile_path=args.profile, dry_run=args.dry_run
        )
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
