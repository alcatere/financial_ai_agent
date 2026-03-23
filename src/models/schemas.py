from typing import Literal, Optional
from pydantic import BaseModel, Field

class Rationale(BaseModel):
    technical_factors: str = Field(description="Explanation of technical indicators (price, volume, trends).")
    fundamental_factors: str = Field(description="Explanation of fundamental indicators (P/E ratio, earnings, revenue).")
    sentiment_factors: str = Field(description="Explanation of news and market sentiment.")

class FinancialRecommendation(BaseModel):
    recommendation: Literal["BUY", "SELL", "HOLD"] = Field(description="The final recommendation for the asset.")
    asset: str = Field(description="The ticker symbol of the asset.")
    confidence: int = Field(ge=0, le=100, description="Confidence level as a percentage (0-100%).")
    rationale: Rationale = Field(description="Detailed reasoning broken down into technical, fundamental, and sentiment factors.")
    risks: str = Field(description="Potential risks associated with this recommendation.")
    suggested_position_size: str = Field(description="Suggested position size (e.g., 'maximum 2% of portfolio').")
    action: str = Field(description="Explain whether to execute trade or wait based on confidence and risk management rules.")
