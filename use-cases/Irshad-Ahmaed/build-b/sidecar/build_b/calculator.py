"""ROI calculator model and SuperDocs report generator for Build B.

Computes build-vs-buy TCO from user inputs, then generates a branded
PDF report via SuperDocs chat + export.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import httpx
from build_a.client import SuperDocsClient, SuperDocsError  # noqa: E402

logger = logging.getLogger(__name__)

# --- TCO model constants (documented in README) ---

DEFAULT_MAINTENANCE_RATE = 0.20  # 20% of initial build hours per year
DEFAULT_INFRA_MONTHLY = 100.0    # $100/month cloud hosting estimate
DEFAULT_HORIZON_YEARS = 3        # 3-year comparison window

SUPERDOCS_TIERS = [
    {"name": "Free", "monthly": 0.0, "max_ops": 500, "max_docs": 500},
    {"name": "Plus", "monthly": 20.0, "max_ops": 2000, "max_docs": 2000},
    {"name": "Pro", "monthly": 99.0, "max_ops": 10000, "max_docs": 10000},
]


@dataclass
class CalculatorInputs:
    """User inputs for the ROI calculator."""

    volume: int           # documents per month
    hours: float          # estimated engineering hours to build
    hourly_cost: float    # loaded hourly cost ($)
    maintenance_rate: float = DEFAULT_MAINTENANCE_RATE
    infrastructure_monthly: float = DEFAULT_INFRA_MONTHLY
    horizon_years: int = DEFAULT_HORIZON_YEARS


@dataclass
class CalculatorResults:
    """Computed TCO results."""

    build_one_time: float
    build_maintenance_annual: float
    build_infra_annual: float
    build_total: float
    buy_annual: float
    buy_total: float
    buy_tier: str
    savings: float
    payback_months: float | None
    inputs: CalculatorInputs


def compute_tco(inputs: CalculatorInputs) -> CalculatorResults:
    """Compute build-vs-buy TCO from user inputs.

    Build cost = (hours × hourly_cost) + (maintenance_rate × hours × hourly_cost × horizon)
                 + (infrastructure_monthly × 12 × horizon)
    Buy cost = SuperDocs tier annual cost × horizon
    """
    if inputs.horizon_years <= 0:
        raise ValueError("horizon_years must be positive")

    build_one_time = inputs.hours * inputs.hourly_cost
    build_maintenance_annual = (
        inputs.maintenance_rate * inputs.hours * inputs.hourly_cost
    )
    build_infra_annual = inputs.infrastructure_monthly * 12
    build_total = (
        build_one_time
        + build_maintenance_annual * inputs.horizon_years
        + build_infra_annual * inputs.horizon_years
    )

    # Select tier based on volume
    tier = SUPERDOCS_TIERS[0]
    for t in SUPERDOCS_TIERS:
        if inputs.volume <= t["max_docs"]:
            tier = t
            break
    else:
        tier = SUPERDOCS_TIERS[-1]

    buy_annual = tier["monthly"] * 12
    buy_total = buy_annual * inputs.horizon_years

    savings = build_total - buy_total

    # Payback: when does the buy path break even vs build?
    if buy_annual > 0:
        net_annual_savings = (build_total - buy_total) / inputs.horizon_years
        payback_months = (buy_total / net_annual_savings) * 12 if net_annual_savings > 0 else None
    else:
        payback_months = None  # free tier — no payback

    return CalculatorResults(
        build_one_time=build_one_time,
        build_maintenance_annual=build_maintenance_annual,
        build_infra_annual=build_infra_annual,
        build_total=build_total,
        buy_annual=buy_annual,
        buy_total=buy_total,
        buy_tier=tier["name"],
        savings=savings,
        payback_months=payback_months,
        inputs=inputs,
    )


class ReportGenerator:
    """Generates a branded PDF report via SuperDocs chat + export."""

    def __init__(self, client: SuperDocsClient) -> None:
        self.client = client

    def build_report_prompt(self, results: CalculatorResults) -> str:
        """Build the exact prompt string with serialized computed values.

        KEY INVARIANT: the prompt contains the exact values from the
        calculator — never recompute server-side.
        """
        payback_str = (
            f"{results.payback_months:.1f} months"
            if results.payback_months is not None
            else "N/A (buy is cheaper)"
        )
        return (
            f"Generate a professional build-vs-buy comparison report. "
            f"Build cost: ${results.build_one_time:,.0f} (one-time) + "
            f"${results.build_maintenance_annual:,.0f}/year maintenance + "
            f"${results.build_infra_annual:,.0f}/year infrastructure. "
            f"Buy cost (SuperDocs {results.buy_tier} plan): "
            f"${results.buy_annual:,.0f}/year. "
            f"Total build cost over {results.inputs.horizon_years} years: "
            f"${results.build_total:,.0f}. "
            f"Total buy cost over {results.inputs.horizon_years} years: "
            f"${results.buy_total:,.0f}. "
            f"Savings: ${results.savings:,.0f}. "
            f"Payback period: {payback_str}. "
            f"Input assumptions: document volume={results.inputs.volume}/month, "
            f"engineering hours={results.inputs.hours}, "
            f"hourly cost=${results.inputs.hourly_cost}, "
            f"infrastructure=${results.inputs.infrastructure_monthly}/month, "
            f"horizon={results.inputs.horizon_years} years."
        )

    async def generate_report(
        self,
        session_id: str,
        results: CalculatorResults,
    ) -> str:
        """Send the report prompt to SuperDocs (1 op).

        Returns the document_changes.updated_html from the response.
        """
        prompt = self.build_report_prompt(results)
        resp = await self.client.edit(message=prompt, session_id=session_id)
        if resp.document_changes and resp.document_changes.updated_html:
            return resp.document_changes.updated_html
        return ""

    async def export_report(
        self,
        session_id: str,
        output_path: Path,
    ) -> Path:
        """Export the report as PDF (0 ops) and save to disk."""
        try:
            result = await self.client.export(session_id=session_id, format="pdf")
            if result.download_url:
                async with httpx.AsyncClient() as http:
                    resp = await http.get(result.download_url)
                    resp.raise_for_status()
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(resp.content)
                    return output_path
        except SuperDocsError:
            pass

        # Fallback: pre-signed URL
        dl = await self.client.request_download(session_id, format="pdf")
        async with httpx.AsyncClient() as http:
            resp = await http.get(dl.download_url)
            resp.raise_for_status()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(resp.content)
            return output_path
