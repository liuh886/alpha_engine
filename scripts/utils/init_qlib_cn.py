from pathlib import Path

from qlib.tests.data import GetData


def main():
    # Define target directory
    project_root = Path(__file__).resolve().parents[2]
    target_dir = project_root / "artifacts" / "archives" / "qlib_demo_data" / "cn"

    print(f"Initializing Qlib CN Data in: {target_dir}")

    # Qlib's GetData automatically handles download and extraction
    # It usually extracts to a subdirectory, so we might need to move things around
    # or just point provider_uri to the right place.

    # Use the qlib_data method which handles naming logic automatically
    GetData().qlib_data(name="qlib_data", region="cn", target_dir=str(target_dir), delete_old=True)

    print("Done. Please verify data exists in:", target_dir)


if __name__ == "__main__":
    main()
