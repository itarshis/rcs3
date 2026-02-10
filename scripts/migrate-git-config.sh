# config.sh - shell-sourced config for split-repo.sh

# Branches to keep (space-separated)
BRANCHES=(itarshis-patch-2 itarshis-patch-1 )

# Directories to keep (top-level directory names, no trailing slashes)
DIRS=( app src )

# Source repo (mirror clone URL)
SRC_REPO="git@github.com:itarshis/rcs3.git"

# Target repo (where branches will be pushed)
TARGET_REPO="git@github.com:itarshis/rcs3-new.git"
    
# If true, push tags to target when --push is used. If false, tags are deleted/never pushed.
PUSH_TAGS=false

# Which branch should become the new main in target (optional)
MAIN_FROM="itarshis-patch-2"    # leave empty to not auto-rename
MAIN_TO="main"          # name to use in target repo

# Temporary working directory (optional). If blank, script will create one under /tmp.
WORKDIR="../tmp-rcs3-split"
