"""The starter questions offered as chips, and what the shipped cache holds for them.

They cover what prompt 6 asks a demo to show: a district comparison, a trend,
leading and lagging, farm harvest against wholesale, one that must carry the
MSP caveat, and one the assistant refuses because the data does not exist.

``reply`` and ``answer`` are what ``python -m app.cli seed-assistant`` records
into the cache as the model's responses. No model key was available when they
were recorded, so they were written by hand against the real result rows and
are recorded with model "fixture"; the answer screen shows that name, so they
are never passed off as model output. Recording checks each one exactly as a
live response is checked: the spec against the registry, and every number in
the answer against the rows. With a key set, a question outside this list goes
to the live model.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class Starter:
    question_id: str
    question: str
    reply: dict[str, Any]
    answer: Optional[str] = None


def _eq(dimension: str, value: str) -> dict[str, Any]:
    return {"dimension": dimension, "op": "eq", "values": [value]}


STARTERS: tuple[Starter, ...] = (
    Starter(
        "district-compare-paddy-yield",
        "Which districts had the highest paddy yield in 2024-25?",
        {
            "action": "query",
            "spec": {
                "metric": "yield_rate",
                "dimensions": ["district"],
                "filters": [_eq("crop", "CR17"), _eq("agri_year", "2024-25")],
                "order_by": {"field": "value", "direction": "desc"},
                "limit": 10,
            },
        },
        "Dhenkanal had the highest paddy yield in 2024-25 at 55.00 qtl/ha, followed by "
        "Bargarh at 53.92 qtl/ha, Subarnapur at 53.64 qtl/ha and Angul at 52.19 qtl/ha. "
        "Koraput (49.48), Cuttack (48.02), Boudh (47.47), Khordha (47.15), Puri (46.80) and "
        "Keonjhar (46.80) complete the ten highest, all in qtl/ha. Yield here is production "
        "divided by area across the seasons, not an average of published yields.",
    ),
    Starter(
        "trend-paddy-production",
        "How has paddy production changed since 1993-94?",
        {
            "action": "query",
            "spec": {
                "metric": "production",
                "dimensions": ["agri_year"],
                "filters": [_eq("crop", "CR17"), _eq("grain_source", "published_state")],
                "period": {"from": "1993-94"},
                "order_by": {"field": "agri_year", "direction": "asc"},
                "limit": 100,
            },
        },
        "State paddy production was 100,260,000 quintals in 1993-94 and 176,240,000 "
        "quintals in 2024-25. The series is uneven rather than steady: it fell to "
        "49,150,000 quintals in 2002-03 and to 89,020,000 quintals in 2015-16, and reached "
        "its highest level of 180,800,000 quintals in 2022-23, with 174,830,000 quintals "
        "in 2023-24.",
    ),
    Starter(
        "leading-lagging-price",
        "Which districts lead and lag on farm-harvest prices for potato in 2018-19?",
        {
            "action": "query",
            "spec": {
                "metric": "avg_price",
                "dimensions": ["district"],
                "filters": [
                    _eq("crop", "CR18"),
                    _eq("price_type", "farm_harvest"),
                    _eq("data_origin", "official"),
                    _eq("agri_year", "2018-19"),
                ],
                "order_by": {"field": "value", "direction": "desc"},
                "limit": 30,
            },
        },
        "In the official 2018-19 figures, Malkangiri led on the farm-harvest price of potato "
        "at 1,583 Rs/quintal, followed by Nayagarh at 1,480 and Boudh at 1,400 Rs/quintal. "
        "Khordha lagged at 815 Rs/quintal, behind Kalahandi at 900 and Kandhamal at 950 "
        "Rs/quintal.",
    ),
    Starter(
        "fhp-wholesale-gap",
        "What is the gap between farm-harvest and wholesale prices?",
        {
            "action": "query",
            "spec": {
                "metric": "fhp_wholesale_gap",
                "dimensions": ["crop"],
                "filters": [_eq("data_origin", "official"), _eq("agri_year", "2018-19")],
                "order_by": {"field": "value", "direction": "desc"},
                "limit": 30,
            },
        },
        "In the official 2018-19 figures, wholesale prices exceeded farm-harvest prices most "
        "for til, by 2,138.77 Rs/quintal, followed by ragi at 579.37 and potato at 468.08 "
        "Rs/quintal. The gap was smallest for paddy at 3.4 Rs/quintal, and wholesale sat "
        "below farm harvest for maize, by 5.21, and groundnut, by 121.73 Rs/quintal. Paddy "
        "prices in the publication are the Minimum Support Price rather than observed "
        "market prices, so the paddy gap does not describe a market.",
    ),
    Starter(
        "paddy-price-msp",
        "What is the average price of paddy in Cuttack?",
        {
            "action": "query",
            "spec": {
                "metric": "avg_price",
                "dimensions": ["agri_year"],
                "filters": [
                    _eq("district", "OD07"),
                    _eq("crop", "CR17"),
                    _eq("price_type", "farm_harvest"),
                    _eq("data_origin", "official"),
                ],
                "order_by": {"field": "agri_year", "direction": "asc"},
                "limit": 100,
            },
        },
        "The official farm-harvest price of paddy in Cuttack rose from 1,310 Rs/quintal in "
        "2013-14 to 1,750 Rs/quintal in 2018-19, passing 1,410 in 2015-16 and 1,550 in "
        "2017-18. These are not observed market prices: the publication records paddy at "
        "the Minimum Support Price, so the series shows what procurement paid rather than "
        "what the market found.",
    ),
    Starter(
        "block-level-prices-declined",
        "What were block-level wholesale prices in Bargarh in 2023-24?",
        {
            "action": "refuse",
            "limitation": (
                "Prices are held at district grain only, so there is no block-level price "
                "for Bargarh or any other district. Official prices also end at 2018-19; "
                "later years exist only as synthetic figures."
            ),
        },
    ),
)

STARTERS_BY_QUESTION = {starter.question: starter for starter in STARTERS}
