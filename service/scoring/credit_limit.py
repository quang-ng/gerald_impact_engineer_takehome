"""
Credit Limit Mapping

Maps risk scores to credit limit buckets for Gerald's BNPL service.

PHILOSOPHY:
-----------
Gerald's $0-fee model requires careful credit limit assignment:

1. Higher limits for lower-risk users: Maximize value for users who will repay
2. Lower limits for moderate-risk users: Provide access while limiting exposure
3. No approval for high-risk users: Better to deny than approve and lose

BUCKET DESIGN:
--------------
The limit buckets are designed around typical user needs:

- $0: Denied - risk too high for $0-fee model viability
- $100: Entry level - for users with thin files or minor risk signals
- $200: Basic - for users with some positive signals
- $300: Standard - for users with good financial health
- $400: Enhanced - for users with strong positive indicators
- $500: Premium - for users with excellent financial health
- $600: Maximum - for lowest-risk users

WHY THESE AMOUNTS:
------------------
- $100-$200: Covers small emergencies (car repair, medical copay)
- $300-$400: Covers moderate expenses (utility catch-up, groceries)
- $500-$600: Covers larger needs (rent gap, insurance deductible)

Gerald caps at $600 because:
- Larger amounts increase default severity without proportional value
- Most users' immediate needs fit within this range
- Keeps repayment manageable (4 installments of $150 max)

SCORE THRESHOLDS:
-----------------
These thresholds are calibrated based on expected default rates:

- Score < 20: Expected default rate >30% - automatic denial
- Score 20-39: Expected default rate 15-30% - minimal limit ($100)
- Score 40-54: Expected default rate 8-15% - conservative limit ($200)
- Score 55-64: Expected default rate 4-8% - standard limit ($300)
- Score 65-74: Expected default rate 2-4% - enhanced limit ($400)
- Score 75-84: Expected default rate 1-2% - premium limit ($500)
- Score 85+: Expected default rate <1% - maximum limit ($600)

TRADE-OFFS:
-----------
- Tighter thresholds = lower approval rate but better unit economics
- Looser thresholds = higher approval rate but more defaults

For $0-fee model, we err conservative because:
- Each default directly impacts bottom line (no fee recovery)
- User experience of denial is better than default + collections
- Trust is built by responsible lending, not by over-extending
"""
from service.logging import get_logger

logger = get_logger(__name__)

# Credit limit buckets in cents
CREDIT_LIMITS = {
    "denied": 0,
    "entry": 10000,      # $100
    "basic": 20000,      # $200
    "standard": 30000,   # $300
    "enhanced": 40000,   # $400
    "premium": 50000,    # $500
    "maximum": 60000,    # $600
}

# Score thresholds (inclusive lower bound)
SCORE_THRESHOLDS = [
    (85, "maximum"),     # 85-100: Maximum limit
    (75, "premium"),     # 75-84: Premium limit
    (65, "enhanced"),    # 65-74: Enhanced limit
    (55, "standard"),    # 55-64: Standard limit
    (40, "basic"),       # 40-54: Basic limit
    (20, "entry"),       # 20-39: Entry limit
    (0, "denied"),       # 0-19: Denied
]


def score_to_credit_limit(score: int) -> tuple[int, str]:
    """
    Map a risk score (0-100) to a credit limit bucket.

    Args:
        score: Risk score from 0 to 100

    Returns:
        Tuple of (credit_limit_cents, band_name)

    Example:
        >>> score_to_credit_limit(85)
        (60000, 'maximum')
        >>> score_to_credit_limit(50)
        (20000, 'basic')
        >>> score_to_credit_limit(15)
        (0, 'denied')
    """
    # Clamp score to valid range
    score = max(0, min(100, score))

    for threshold, band in SCORE_THRESHOLDS:
        if score >= threshold:
            limit = CREDIT_LIMITS[band]
            logger.debug(
                "credit_limit_mapped",
                score=score,
                threshold=threshold,
                band=band,
                limit_cents=limit,
            )
            return limit, band

    # Fallback (should never reach here)
    return 0, "denied"


def get_amount_granted(credit_limit_cents: int, requested_cents: int) -> int:
    """
    Calculate the amount to grant based on credit limit and request.

    The granted amount is the minimum of:
    - The requested amount
    - The user's credit limit

    Args:
        credit_limit_cents: User's approved credit limit
        requested_cents: Amount the user requested

    Returns:
        Amount to grant in cents
    """
    return min(credit_limit_cents, requested_cents)
