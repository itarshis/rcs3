#!/usr/bin/env bash
set -euo pipefail

# Usage: ./split-repo.sh path/to/config.sh [--push]
# --push    : actually push branches (and tags if configured) to TARGET_REPO
# --help    : show help

###############################################################################
# Helpers
###############################################################################
info() { printf "\033[1;34m[INFO]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[WARN]\033[0m %s\n" "$*"; }
err()  { printf "\033[1;31m[ERROR]\033[0m %s\n" "$*" >&2; exit 1; }

###############################################################################
# Parse args
###############################################################################
PUSH=false
if [[ "${1:-}" == "" || "${1:-}" == "--help" ]]; then
  echo "Usage: $0 path/to/config.sh [--push]"
  echo
  echo "Config file format: shell file that sets BRANCHES, DIRS, SRC_REPO, TARGET_REPO, PUSH_TAGS"
  exit 1
fi

CONFIG="$1"
shift || true

while [[ ${#@} -gt 0 ]]; do
  case "$1" in
    --push) PUSH=true; shift ;;
    --help) echo "Usage: $0 path/to/config.sh [--push]"; exit 0 ;;
    *) err "Unknown arg: $1" ;;
  esac
done

###############################################################################
# Load config
###############################################################################
if [[ ! -f "$CONFIG" ]]; then
  err "Config file not found: $CONFIG"
fi

# shellcheck source=/dev/null
source "$CONFIG"

# Validate required variables
: "${BRANCHES:?BRANCHES must be set in config (array)}"
: "${DIRS:?DIRS must be set in config (array)}"
: "${SRC_REPO:?SRC_REPO must be set in config}"
: "${TARGET_REPO:?TARGET_REPO must be set in config}"
: "${PUSH_TAGS:=false}"

# optional MAIN_FROM/MAIN_TO
MAIN_FROM="${MAIN_FROM:-}"
MAIN_TO="${MAIN_TO:-main}"

WORKDIR="${WORKDIR:-}"

###############################################################################
# Prepare working dir
###############################################################################
if [[ -z "$WORKDIR" ]]; then
  WORKDIR="$(mktemp -d /tmp/rocky-split.XXXXXX)"
fi

info "Working directory: $WORKDIR"
cd "$WORKDIR"

MIRROR_DIR="$WORKDIR/old-rocky.git"

###############################################################################
# Step 1: mirror clone
###############################################################################
info "Cloning mirror of source repository: $SRC_REPO"
git clone --mirror "$SRC_REPO" "$MIRROR_DIR"
cd "$MIRROR_DIR"

info "Listing branches found in mirror:"
git for-each-ref --format='%(refname:short)' refs/heads | sed 's/^/  - /' || true

###############################################################################
# Step 2: detach from source remote (safety)
###############################################################################
info "Removing original remotes to avoid accidental pushes"
# commonly origin exists in mirror; remove it to be safe
set +e
git remote remove origin 2>/dev/null || true
set -e
info "No remote named 'origin' in this mirror (safe to proceed)"

###############################################################################
# Step 3: prune to only requested branches (optional but faster)
###############################################################################
info "Pruning branches: will keep: ${BRANCHES[*]}"
# delete every branch not in BRANCHES
for b in $(git for-each-ref --format='%(refname:short)' refs/heads); do
  keep=false
  for kb in "${BRANCHES[@]}"; do
    if [[ "$b" == "$kb" ]]; then keep=true; break; fi
  done
  if [[ "$keep" == false ]]; then
    info "Deleting branch ref $b from mirror"
    git update-ref -d "refs/heads/$b"
  fi
done

info "Branches remaining after prune:"
git for-each-ref --format='%(refname:short)' refs/heads | sed 's/^/  - /' || true

###############################################################################
# Step 4: rewrite history to keep only specified directories (top-level)
###############################################################################
info "Rewriting history to keep only directories: ${DIRS[*]}"
# Build the reset path list
RESET_PATHS=""
for d in "${DIRS[@]}"; do
  RESET_PATHS+=" $d"
done

# Use git filter-branch (core git). This is destructive to the mirror only.
git filter-branch --prune-empty --index-filter \
  "git rm -r --cached --ignore-unmatch . >/dev/null 2>&1 || true; git reset -q \$GIT_COMMIT --${RESET_PATHS}" \
  -- --all

info "Filter-branch complete."

###############################################################################
# Step 5: handle tags
###############################################################################
if [[ "$PUSH_TAGS" == "true" || "$PUSH_TAGS" == "True" || "$PUSH_TAGS" == "1" ]]; then
  TAG_POLICY="preserve"
else
  TAG_POLICY="drop"
fi
info "Tag policy: $TAG_POLICY"

if [[ "$TAG_POLICY" == "drop" ]]; then
  info "Deleting tags in the mirror to avoid accidental pushes that would trigger workflows"
  for t in $(git for-each-ref --format='%(refname)' refs/tags || true); do
    git update-ref -d "$t" || true
  done
fi

###############################################################################
# Step 6: cleanup local refs
###############################################################################
info "Cleaning up backup refs and running garbage collection (may take a while)"
rm -rf refs/original/ || true
git reflog expire --expire=now --all || true
git gc --prune=now --aggressive || true

###############################################################################
# Step 7: Summary / Dry-run report
###############################################################################
info "Preparing report of what will be pushed (dry-run)."

echo
echo "==================== REPORT ===================="
echo "Source repo: $SRC_REPO"
echo "Target repo: $TARGET_REPO"
echo "Working mirror: $MIRROR_DIR"
echo "Branches to push: ${BRANCHES[*]}"
echo "Directories preserved at top-level: ${DIRS[*]}"
echo "Tag policy: $TAG_POLICY"
if [[ -n "$MAIN_FROM" ]]; then
  echo "Configured to rename branch '$MAIN_FROM' -> '$MAIN_TO' in target if --push provided."
fi
echo "================================================"
echo

# For each branch, show the root dirs present in tip of that branch
for b in "${BRANCHES[@]}"; do
  if git rev-parse --verify "refs/heads/$b" >/dev/null 2>&1; then
    commit=$(git rev-parse "refs/heads/$b")
    echo "Branch: $b (HEAD $commit)"
    echo "Top-level entries:"
    git ls-tree --name-only "refs/heads/$b" | sed 's/^/  - /' || true
    echo
  else
    warn "Branch $b not present in mirror (it may have been pruned earlier)"
  fi
done

###############################################################################
# Step 8: If not pushing, finish here; else add remote and push
###############################################################################
if [[ "$PUSH" != true ]]; then
  warn "No --push flag provided. The script has performed the local rewriting and printed a report."
  warn "To actually push to the target repo, re-run with --push."
  echo
  echo "Suggested push commands (will push only branches and, optionally, tags):"
  for b in "${BRANCHES[@]}"; do
    echo "  git push $TARGET_REPO refs/heads/$b:refs/heads/$b"
  done
  if [[ -n "$MAIN_FROM" ]]; then
    echo "  # Optionally push the MAIN_FROM as MAIN_TO in one command:"
    echo "  git push $TARGET_REPO refs/heads/$MAIN_FROM:refs/heads/$MAIN_TO"
  fi
  if [[ "$TAG_POLICY" == "preserve" ]]; then
    echo "  # To push tags: git push $TARGET_REPO --tags"
  else
    echo "  # Tags were removed and will NOT be pushed."
  fi
  echo
  echo "Mirror repository left at: $MIRROR_DIR (you can remove it when you're satisfied)"
  exit 0
fi

###############################################################################
# Step 9: Add target remote and push
###############################################################################
info "--push requested: adding remote for target and pushing branches"

git remote add target "$TARGET_REPO"
git pull target

# push branches
for b in "${BRANCHES[@]}"; do
  push_branch target "$b"
done

# Optionally push MAIN_FROM as MAIN_TO (single ref update)
if [[ -n "$MAIN_FROM" ]]; then
  if git rev-parse --verify "refs/heads/$MAIN_FROM" >/dev/null 2>&1; then
    info "Pushing branch $MAIN_FROM as $MAIN_TO on target"
    push_branch target "$MAIN_FROM"
  else
    warn "MAIN_FROM branch $MAIN_FROM not present; skipping main rename push."
  fi
fi

# tags
if [[ "$TAG_POLICY" == "preserve" ]]; then
  info "Pushing tags to target"
  git push target --tags
else
  info "Tags are not pushed per config"
fi

info "Push complete."

echo
echo "FINAL NOTE:"
echo " - Please set default branch on $TARGET_REPO (if needed) to $MAIN_TO via GitHub UI or API."
echo " - Review Actions/workflows in the target repo to ensure triggers are correct."
echo
echo "Mirror repository left at: $MIRROR_DIR (remove when you're sure):"
echo "  rm -rf '$MIRROR_DIR'"

exit 0


push_branch() {
  local remote="$1"   # e.g. target
  local branch="$2"   # e.g. branch-2
  local local_ref="refs/heads/$branch"

  if ! git rev-parse --verify "$local_ref" >/dev/null 2>&1; then
    warn "Local branch $branch missing; skipping"
    return 0
  fi

  local local_sha
  local_sha="$(git rev-parse "$local_ref")"

  # Query remote SHA (empty if branch doesn't exist)
  local remote_line remote_sha
  remote_line="$(git ls-remote --heads "$remote" "$branch" || true)"
  remote_sha="$(awk '{print $1}' <<<"$remote_line")"

  if [[ -z "$remote_sha" ]]; then
    info "Remote branch $branch does not exist. Pushing new branch."
    git push -u "$remote" "$local_ref:refs/heads/$branch"
    return 0
  fi

  if [[ "$remote_sha" == "$local_sha" ]]; then
    info "Remote branch $branch already matches (idempotent no-op)."
    return 0
  fi

  # If remote is ancestor of local, a normal push is fine
  if git merge-base --is-ancestor "$remote_sha" "$local_sha"; then
    info "Remote branch $branch can fast-forward. Pushing."
    git push -u "$remote" "$local_ref:refs/heads/$branch"
    return 0
  fi

  # Diverged histories
  warn "Remote branch $branch has different history (diverged)."
  warn "  remote: $remote_sha"
  warn "  local : $local_sha"

  if [[ "${PUSH_MODE:-safe}" == "migrate" ]]; then
    if [[ "${ALLOW_NONEMPTY_TARGET:-false}" != "true" ]]; then
      err "Refusing to overwrite remote in migrate mode because ALLOW_NONEMPTY_TARGET is not true."
    fi
    info "Overwriting remote branch $branch using --force-with-lease (migration mode)."
    git push --force-with-lease="$branch:$remote_sha" "$remote" "$local_ref:refs/heads/$branch"
  else
    warn "Safe mode: skipping push for $branch. (Set PUSH_MODE=migrate to overwrite.)"
  fi
}
