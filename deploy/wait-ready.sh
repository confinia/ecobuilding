#!/bin/bash
# Wait until an environment actually answers, before any e2e assertion (#345).
#
# A stack that has just been recreated is not a stack that is ready: the API
# is still opening its sockets, and the edge may still be issuing a
# certificate. The e2e scripts used to fire straight at the public host with
# fixed curl budgets, so a change that touched no code got a red pipeline and
# a failure e-mail — the same erosion of trust as a noisy alert (#343). Same
# idea as the smoke grace window (#304): tolerate the start-up, never the
# failure. Sourced, so callers get `attendre_pret` in their shell.
attendre_pret() {
  local base="${1:?usage: attendre_pret <base-url> [seconds]}"
  local budget="${2:-90}"
  local t0=$SECONDS
  until curl -fsS -m 5 -o /dev/null "$base/api/v1/healthz" 2>/dev/null; do
    if (( SECONDS - t0 >= budget )); then
      echo "wait-ready: $base n'a pas répondu en ${budget}s — échec réel" >&2
      return 1
    fi
    sleep 3
  done
  local mis=$(( SECONDS - t0 ))
  (( mis > 0 )) && echo "wait-ready: $base prêt après ${mis}s"
  return 0
}
