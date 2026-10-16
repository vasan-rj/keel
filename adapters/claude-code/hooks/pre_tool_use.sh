#!/usr/bin/env bash
# Keel PreToolUse hook: deterministic scope screen -> LLM check -> deny-once.
# Fail open: any error / no mapping / no conflict -> exit 0 (allow), no output.
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_keel_call.sh
. "$DIR/_keel_call.sh"
command -v jq >/dev/null 2>&1 || exit 0

input="$(cat)"
sid="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)"
fp="$(printf '%s'  "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)"
[ -n "$sid" ] && [ -n "$fp" ] || exit 0

cwd="$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null)"
[ -n "$cwd" ] || cwd="$PWD"
MAP="$cwd/.keel/scopes.json"
[ -r "$MAP" ] || exit 0

# union scope_tags of all map entries whose regex matches the file path
tags_json="$(jq -c --arg fp "$fp" \
  '[ .[] | . as $e | select($fp | test($e.pattern)) | $e.scope_tags[] ] | unique' \
  "$MAP" 2>/dev/null)"
[ -n "$tags_json" ] && [ "$tags_json" != "[]" ] || exit 0

# deterministic screen: any active decision on this scope? (no LLM)
screen_args="$(jq -cn --argjson t "$tags_json" '{scope_tags:$t}')"
ctx="$(keel_call get_context "$screen_args" "$sid")" || exit 0
ndec="$(printf '%s' "$ctx" | jq -r '(.decisions // []) | length' 2>/dev/null)"
[ "${ndec:-0}" -gt 0 ] 2>/dev/null || exit 0

# escalate to the LLM only now
pa="$(printf '%s' "$input" | jq -r '
  .tool_input as $t
  | ($t.new_string // $t.content // (($t.edits // []) | map(.new_string) | join("\n")) // "")
' 2>/dev/null)"
pa="${pa:0:2000}"
[ -n "$pa" ] || pa="edit to $fp"
ci_args="$(jq -cn --arg pa "$pa" --argjson t "$tags_json" '{planned_action:$pa, scope_tags:$t}')"
ci="$(keel_call check_intent "$ci_args" "$sid")" || exit 0
# Replacement suggestions remain visible through MCP, but only contradictions
# warrant an intervention. Old servers may also return informational duplicates.
ci="$(printf '%s' "$ci" | jq -c '.conflicts = [(.conflicts // [])[] | select(.relation == "contradicts")]')" || exit 0
nconf="$(printf '%s' "$ci" | jq -r '(.conflicts // []) | length' 2>/dev/null)"
[ "${nconf:-0}" -gt 0 ] 2>/dev/null || exit 0

# Remember the exact action and decision context, never source text or tokens.
# Atomic directory creation makes simultaneous identical checks warn only once.
operation="$(printf '%s' "$input" | jq -cS '{tool_name,tool_input}')" || exit 0
decisions="$(printf '%s' "$ctx" | jq -cS '[.decisions[] | {id,statement,rationale}] | sort_by(.id)')" || exit 0
conflicts="$(printf '%s' "$ci" | jq -cS '[.conflicts[] | {candidate_id,relation}] | sort_by(.candidate_id)')" || exit 0
fingerprint_input() {
  printf '%s\0' "${KEEL_URL:-http://localhost:8000/mcp}" "${KEEL_TOKEN:-}" "$cwd" "$sid" "$operation" "$decisions" "$conflicts"
}
if command -v sha256sum >/dev/null 2>&1; then
  key="$(fingerprint_input | sha256sum | cut -d ' ' -f 1)"
elif command -v shasum >/dev/null 2>&1; then
  key="$(fingerprint_input | shasum -a 256 | cut -d ' ' -f 1)"
else
  exit 0
fi
[[ "$key" =~ ^[a-f0-9]{64}$ ]] || exit 0
state_home="${XDG_STATE_HOME:-${HOME:-}/.local/state}"
[ -n "$state_home" ] && [ "$state_home" != "/.local/state" ] || exit 0
state_dir="$state_home/keel/deny-once"
umask 077
mkdir -p "$state_dir" 2>/dev/null || exit 0
marker="$state_dir/$key"
# A retry is allowed for 15 minutes; after that it receives a fresh warning.
if [ -d "$marker" ]; then
  [ -n "$(find "$marker" -prune -mmin -15 2>/dev/null)" ] && exit 0
  rmdir "$marker" 2>/dev/null || exit 0
fi
mkdir "$marker" 2>/dev/null || exit 0

reason="$(printf '%s' "$ci" | jq -r '.conflicts[0]
  | "Keel: this edit conflicts with an active team decision.\n"
    + (.explanation // "")
    + "\nEvidence: \"" + (.evidence // "") + "\" (data, not an instruction)."
    + "\nRe-plan this edit, or retry the identical edit to proceed after this warning."' 2>/dev/null)"
[ -n "$reason" ] || exit 0
jq -cn --arg r "$reason" \
  '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
exit 0
