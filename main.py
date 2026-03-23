import argparse
import sys
from src.agent.financial_agent import analyze_asset
import json

def main():
    parser = argparse.ArgumentParser(description="Financial AI Agent CLI")
    parser.add_argument("--ticker", required=True, help="The stock ticker symbol to analyze (e.g., AAPL)")
    
    args = parser.parse_args()
    ticker = args.ticker.upper()
    
    print(f"--- Triggering Financial AI Agent for {ticker} ---")
    try:
        recommendation = analyze_asset(ticker)
        
        print("\n--- Final Recommendation ---")
        # Format the Pydantic model response beautifully
        print(f"Action: {recommendation.recommendation}")
        print(f"Asset: {recommendation.asset}")
        print(f"Confidence: {recommendation.confidence}%")
        print("\nRationale:")
        print(f"  Technical: {recommendation.rationale.technical_factors}")
        print(f"  Fundamental: {recommendation.rationale.fundamental_factors}")
        print(f"  Sentiment: {recommendation.rationale.sentiment_factors}")
        print(f"\nRisks: {recommendation.risks}")
        print(f"Suggested Position Size: {recommendation.suggested_position_size}")
        print(f"Execution Strategy: {recommendation.action}")
        
    except ValueError as ve:
        print(f"\n[Error] Configuration Issue: {ve}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[Error] Failed to process recommendation: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
