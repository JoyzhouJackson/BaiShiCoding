"""PyCharm entry point: validate first, then solve the fixed 12-case V6 set."""

from run_all import main


if __name__ == "__main__":
    main(
        method="benders-cg",
        result_set="benders_cg_v6_12",
        verification_script="run_benders_cg_verification.py",
    )
