import os

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

load_dotenv()

api_key = os.getenv("LITELLM_API_KEY")

client = OpenAI(
    base_url="https://www.litellm.org/",
    api_key=api_key,
)


class FinancialReport(BaseModel):
    company_name: str
    revenue: float
    yoy_growth: float
    risk_factors: list[str]


content = """
Tesla First Quarter 2026 Production, Deliveries & Deployments
Business Wire
Apr 2, 2026
AUSTIN, Texas, April 2, 2026 – In the first quarter, we produced over 408,000 vehicles, delivered over 358,000 vehicles and deployed 8.8 GWh of energy storage products.

Thank you to all of our customers, employees, suppliers, shareholders and supporters who helped us achieve these results.

Q1 2026

 	Production	Deliveries	Subject to operating lease accounting
Model 3/Y	394,611	341,893	1%
Other Models	13,775	16,130	2%
Total	408,386	358,023	1%
"""

response = client.responses.parse(
    model="azure/gpt-5-mini",
    input=[
        {"role": "system", "content": "Extract the event information."},
        {
            "role": "user",
            "content": content,
        },
    ],
    text_format=FinancialReport,
)

event = response.output_parsed
print(event)
