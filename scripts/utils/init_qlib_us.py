from pathlib import Path

from qlib.tests.data import GetData


def main():
    # Define target directory
    project_root = Path(__file__).resolve().parents[2]
    target_dir = project_root / "artifacts" / "archives" / "qlib_demo_data" / "us"

    print(f"Initializing Qlib US Data in: {target_dir}")

    # Use the qlib_data method which handles naming logic automatically
    try:
        GetData().qlib_data(
            name="qlib_data", region="us", target_dir=str(target_dir), delete_old=True
        )
        print("Done. Please verify data exists in:", target_dir)
    except Exception as e:
        print(f"Error downloading US data: {e}")
        print(
            "Fallback: You may need to manually download CrowdSource data or similar for US equities."
        )


if __name__ == "__main__":
    main()
