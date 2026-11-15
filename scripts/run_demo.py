import argparse
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fintech_promo import PaymentEvent, run


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-seconds", type=float, default=1800)
    parser.add_argument("--bucket", default="fintech-promos")
    args = parser.parse_args()
    event = PaymentEvent("Northstar Card", 12900, "USD", "medium", True)
    print(run(event, bucket=args.bucket, timeout_seconds=args.timeout_seconds))
