import argparse
import sys

from src.config import load_config


def cmd_analyze(args):
    from src.pipeline import run_analysis
    config = load_config()
    print(f"--- Running in {config.mode_label} mode, execution={config.execution_mode} ---")
    run_analysis(args.ticker.upper(), config)


def cmd_check_confirmations(args):
    from src.pipeline import run_check_confirmations
    config = load_config()
    print(f"--- Checking Telegram confirmations ({config.mode_label} mode) ---")
    run_check_confirmations(config)


def main():
    parser = argparse.ArgumentParser(description="Financial AI Agent CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser("analyze", help="Analyze a ticker and propose/execute an order")
    analyze_parser.add_argument("--ticker", required=True, help="The stock ticker symbol to analyze (e.g., AAPL)")
    analyze_parser.set_defaults(func=cmd_analyze)

    check_parser = subparsers.add_parser("check-confirmations", help="Poll Telegram for order confirmations and execute them")
    check_parser.set_defaults(func=cmd_check_confirmations)

    args = parser.parse_args()

    try:
        args.func(args)
    except ValueError as ve:
        print(f"\n[Error] Configuration Issue: {ve}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[Error] Failed to process request: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
