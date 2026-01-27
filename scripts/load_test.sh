#!/usr/bin/env bash
# Generates traffic against the decision endpoint to populate Datadog dashboard.
# Usage: ./scripts/load_test.sh [rounds] [delay]
#   rounds: number of loops (default: 20)
#   delay:  seconds between rounds (default: 2)

BASE_URL="${BASE_URL:-http://localhost:8000}"
ROUNDS="${1:-20}"
DELAY="${2:-2}"

USERS=("user_good" "user_gig" "user_overdraft" "user_highutil" "user_thin")
AMOUNTS=(10000 20000 30000 40000 50000 60000)

echo "Sending $ROUNDS rounds of requests to $BASE_URL (${#USERS[@]} users × random amounts)"
echo "---"

for ((i=1; i<=ROUNDS; i++)); do
  for user in "${USERS[@]}"; do
    amount=${AMOUNTS[$((RANDOM % ${#AMOUNTS[@]}))]}
    status=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/v1/decision" \
      -H "Content-Type: application/json" \
      -d "{\"user_id\": \"$user\", \"amount_cents_requested\": $amount}")
    echo "[$i/$ROUNDS] $user  amount=$amount  status=$status"
  done

  # Also hit health endpoint for general HTTP metrics
  curl -s -o /dev/null "$BASE_URL/health"

  if [ "$i" -lt "$ROUNDS" ]; then
    sleep "$DELAY"
  fi
done

echo "---"
echo "Done. Sent $((ROUNDS * ${#USERS[@]})) decision requests."
echo "Check dashboard in ~1-2 minutes: https://us5.datadoghq.com/dashboard/adi-xym-yj9/gerald-bnpl-decision-service"
