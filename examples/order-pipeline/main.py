"""Runnable demo of the order-pipeline example.

Prereqs:
  - `docker compose up -d --build` from this directory.
  - `pip install google-cloud-bigquery google-cloud-storage \
       google-cloud-secret-manager google-cloud-pubsub google-cloud-firestore`
    (or `pip install -e ".[dev]"` from the repo root).

Run:
  python main.py
"""

from __future__ import annotations

from order_pipeline import OrderPipeline


def main() -> None:
    print("Connecting to gcp-local emulator on localhost…")
    pipeline = OrderPipeline()
    print("✓ emulator healthy\n")

    print("Setting up: secret, GCS bucket, BigQuery dataset+table, Pub/Sub topic…")
    pipeline.setup()
    print("✓ setup complete\n")

    orders = [
        ("order-1001", "alice", 42.50, "widget"),
        ("order-1002", "alice", 18.75, "bolt"),
        ("order-1003", "bob", 100.00, "gear"),
        ("order-1004", "bob", 12.25, "spring"),
        ("order-1005", "carol", 77.00, "axle"),
    ]
    for order_id, customer, amount, item in orders:
        print(f"Placing {order_id}: {customer} {amount:.2f} {item}")
        pipeline.place_order(order_id=order_id, customer=customer, amount=amount, item=item)
    print()

    print("Confirming pending orders via Pub/Sub pull…")
    n = pipeline.confirm_pending_orders(timeout_s=5.0)
    print(f"✓ confirmed {n} orders\n")

    print("Daily totals (BigQuery aggregate):")
    for customer, total in pipeline.daily_totals().items():
        print(f"  {customer:10s} {total:8.2f}")


if __name__ == "__main__":
    main()
