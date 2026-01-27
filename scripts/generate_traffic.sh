#!/usr/bin/env bash
# Generates diverse traffic to populate all dashboard metrics.
# Usage: ./scripts/generate_traffic.sh [rounds] [delay]

BASE_URL="${BASE_URL:-http://localhost:8000}"
ROUNDS="${1:-30}"
DELAY="${2:-0.5}"

USERS=("user_good" "user_gig" "user_overdraft" "user_highutil" "user_thin")
AMOUNTS=(10000 20000 30000 40000 50000 60000)

TOTAL=0
APPROVED=0
DENIED=0

echo "============================================="
echo "  Gerald BNPL — Traffic Generator"
echo "============================================="
echo "Target:  $BASE_URL"
echo "Rounds:  $ROUNDS"
echo "Users:   ${USERS[*]}"
echo "============================================="
echo ""

for ((i=1; i<=ROUNDS; i++)); do
  for user in "${USERS[@]}"; do
    amount=${AMOUNTS[$((RANDOM % ${#AMOUNTS[@]}))]}

    response=$(curl -s -X POST "$BASE_URL/v1/decision" \
      -H "Content-Type: application/json" \
      -d "{\"user_id\": \"$user\", \"amount_cents_requested\": $amount}")

    approved=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('approved','?'))" 2>/dev/null)
    score=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('decision_factors',{}).get('risk_score','?'))" 2>/dev/null)
    limit=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('credit_limit_cents',0))" 2>/dev/null)

    TOTAL=$((TOTAL + 1))
    if [ "$approved" = "True" ]; then
      APPROVED=$((APPROVED + 1))
      symbol="✓"
    else
      DENIED=$((DENIED + 1))
      symbol="✗"
    fi

    printf "[%3d/%d] %s %-16s amt=\$%-3d score=%-3s limit=\$%-4s\n" \
      "$i" "$ROUNDS" "$symbol" "$user" "$((amount/100))" "$score" "$((limit/100))"
  done

  # Hit health + metrics endpoints for HTTP metrics variety
  curl -s -o /dev/null "$BASE_URL/health"
  curl -s -o /dev/null "$BASE_URL/metrics"

  # Occasionally send bad requests to generate 422 errors
  if (( RANDOM % 5 == 0 )); then
    curl -s -o /dev/null -X POST "$BASE_URL/v1/decision" \
      -H "Content-Type: application/json" \
      -d '{"user_id": "", "amount_cents_requested": 0}'
    curl -s -o /dev/null -X POST "$BASE_URL/v1/decision" \
      -H "Content-Type: application/json" \
      -d '{"bad_field": true}'
  fi

  if [ "$i" -lt "$ROUNDS" ]; then
    sleep "$DELAY"
  fi
done

echo ""
echo "============================================="
echo "  Summary"
echo "============================================="
echo "Total requests:  $TOTAL"
echo "Approved:        $APPROVED"
echo "Denied:          $DENIED"
if [ "$TOTAL" -gt 0 ]; then
  RATE=$((APPROVED * 100 / TOTAL))
  echo "Approval rate:   ${RATE}%"
fi
echo ""
echo "Metrics endpoint:  $BASE_URL/metrics"
echo "Dashboard:         https://us5.datadoghq.com/dashboard/adi-xym-yj9/gerald-bnpl-decision-service"
echo ""
echo "Data should appear in Datadog within 1-2 minutes."
