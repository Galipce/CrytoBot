#!/bin/sh
# Stop hook: at the end of every turn, writes .claude/handoff.local.md — where the work stands, so
# another tool (or a new session) can resume from files (spec 0027, Req. 7).
# Derived only from files and git: stdin (the turn's transcript) is never read. Untracked
# (.claude/.gitignore). Written to a temp file and moved into place. Any failure is silent and
# never blocks the turn: every path exits 0. settings.json caps it at 2 s ("timeout": 2).

write_note() {
  root=${CLAUDE_PROJECT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)}
  cd "$root" || return 1
  [ -d .claude ] || return 1
  note=.claude/handoff.local.md
  tmp=$note.tmp.$$
  git() { command git --no-optional-locks "$@"; }

  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || branch="(no git)"
  head=$(git log -1 --format='%h %s' 2>/dev/null) || head="(no commit)"
  number=$(printf '%s\n' "$branch" | sed -n 's|^[^/]*/\([0-9][0-9][0-9][0-9]\)-.*|\1|p')

  {
    echo "# Handoff note"
    echo ""
    echo "Otomatik: Claude Code Stop hook'u (.claude/hooks/handoff-note.sh). Yalnızca dosyalardan ve git'ten;"
    echo "sohbet içermez. Kayıtlı branch ya da HEAD şimdikinden farklıysa not eskidir."
    echo ""
    echo "- Written: $(date '+%Y-%m-%d %H:%M:%S %z')"
    echo "- Branch: $branch"
    echo "- HEAD: $head"
    echo ""
    echo "## Active specs"
    found=0
    for s in specs/active/[0-9]*.md; do
      [ -f "$s" ] || continue
      found=1
      status=$(sed -n 's/^- Status: *//p' "$s" | head -n 1 | tr -d '\r')
      echo "- $s — Status: ${status:-?}"
    done
    [ "$found" -eq 1 ] || echo "- (none)"
    echo ""
    plan=specs/plans/$number-plan.md
    if [ -n "$number" ] && [ -f "$plan" ]; then
      echo "## Plan ($plan)"
      approved=$(sed -n 's/^- Approved by \/ on: *//p' "$plan" | head -n 1 | tr -d '\r')
      echo "- Approved by / on: ${approved:-—}"
      # First unfinished step: the first k with no "[plan NNNN/k]" commit in HEAD's history.
      log=$(git log -F --grep="[plan $number/" --format=%B HEAD 2>/dev/null)
      next=$(sed -n '/^## Ordered steps/,/^## /p' "$plan" | tr -d '\r' | sed -n 's/^\([0-9][0-9]*\)\. \(.*\)/\1 \2/p' |
        while IFS=' ' read -r k rest; do
          printf '%s\n' "$log" | grep -qF "[plan $number/$k]" && continue
          title=$(printf '%s\n' "$rest" | sed -n 's/^\*\*\([^*]*\)\*\*.*/\1/p')
          echo "$k. ${title:-$rest}"
          break
        done)
      echo "- First unfinished step: ${next:-(every step has its commit)}"
    else
      echo "## Plan"
      echo "- (no plan matches the branch number${number:+ $number})"
    fi
    echo ""
    echo "## Uncommitted changes (git status --porcelain)"
    changes=$(git status --porcelain 2>/dev/null)
    if [ -n "$changes" ]; then printf '%s\n' "$changes" | sed 's/^/    /'; else echo "- (clean)"; fi
  } > "$tmp" 2>/dev/null || { rm -f "$tmp"; return 1; }
  [ ! -d "$note" ] && mv -f "$tmp" "$note" 2>/dev/null || { rm -f "$tmp"; return 1; }
}

write_note >/dev/null 2>&1 < /dev/null
exit 0
