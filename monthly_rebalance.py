"""
Monthly Rebalance Automation
=============================
Runs the existing scoring engine and generates a dated PDF snapshot, with no
user interaction. Intended to be triggered by cron on the 1st of each month.

RUN MANUALLY:
    python3 monthly_rebalance.py

SCHEDULE (cron, runs at 9am on the 1st of each month):
    0 9 1 * * cd /Users/thomasmacbook/Desktop/Pmanager && /usr/bin/python3 monthly_rebalance.py >> monthly_rebalance.log 2>&1
"""

import portfolio_app


def get_scoreable_holdings(data):
    return [
        h for h in data.get("main", []) + data.get("trial", [])
        if h.get("ticker") and float(h.get("shares") or 0) > 0
    ]


def main():
    data = portfolio_app.load_data()
    holdings = get_scoreable_holdings(data)
    result = portfolio_app.run_scoring(holdings)
    if "error" in result:
        print(f"Skipped: {result['error']}")
        return
    path = portfolio_app.generate_pdf_report(result)
    print(f"Saved monthly report to {path}")


if __name__ == "__main__":
    main()
