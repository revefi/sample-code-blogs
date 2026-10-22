#!/bin/bash
# Run every scenario RUNS_PER_SCENARIO times (scenarios in parallel, repeats sequential), then aggregate.
set -u
cd "$(dirname "$0")" || exit 1
if [ -f .env ]; then set -a; . ./.env; set +a; fi
N=$(python3 -c "import config; print(config.RUNS_PER_SCENARIO)")
SCENARIOS=$(python3 -c "import config; print(' '.join(config.SCENARIOS))")
for scenario in ${@:-$SCENARIOS}; do
  (for i in $(seq 1 "$N"); do python3 agent.py --scenario "$scenario" --idx "$i"; done) &
done
wait
python3 aggregate.py
