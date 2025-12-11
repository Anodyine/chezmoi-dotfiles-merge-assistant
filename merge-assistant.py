#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
import argparse
from pathlib import Path

# --- Configuration ---
DEFAULT_BRANCH = "compare-external"
EXTERNAL_DIR = ".external_sources"
TEMP_TAR = "/tmp/incoming_dots.tar"

# Items to delete before import to ensure clean state
CHEZMOI_PREFIXES = (
    "dot_", "private_", "executable_", "exact_", "symlink_", 
    "modify_", "create_", "empty_", "readonly_"
)

def run_cmd(cmd, cwd=None, exit_on_fail=True):
    try:
        subprocess.run(cmd, shell=True, check=True, cwd=cwd)
    except subprocess.CalledProcessError:
        print(f"\n[!] Error running command: {cmd}")
        if exit_on_fail: sys.exit(1)

def get_current_branch(cwd):
    return subprocess.check_output(["git", "branch", "--show-current"], cwd=cwd).decode().strip()

def get_git_root(path):
    try:
        # Check if inside a submodule
        super_root = subprocess.check_output(
            ["git", "rev-parse", "--show-superproject-working-tree"], 
            cwd=path, stderr=subprocess.DEVNULL
        ).decode().strip()
        if super_root: return Path(super_root)
        
        # Normal repo root
        return Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=path).decode().strip())
    except:
        print("[!] Error: Must be run inside a git repository.")
        sys.exit(1)

def parse_arguments():
    parser = argparse.ArgumentParser(description="Chezmoi Merge Assistant")
    parser.add_argument("--repo", "-r", required=True, help="GitHub URL of dotfiles repo")
    parser.add_argument("--path", "-p", default=".", help="Path inside repo (default: root)")
    parser.add_argument("--branch", "-b", default=DEFAULT_BRANCH, help="Branch name")
    return parser.parse_args()

def main():
    args = parse_arguments()
    inner_path = args.path.strip("/")
    git_treeish = "HEAD" if inner_path in ["", "."] else f"HEAD:{inner_path}"

    script_location = Path(__file__).parent.resolve()
    source_dir = get_git_root(script_location)
    
    repo_name = args.repo.split("/")[-1].replace(".git", "")
    submodule_rel_path = os.path.join(EXTERNAL_DIR, repo_name)
    submodule_full_path = source_dir / submodule_rel_path

    print(f"--- Chezmoi Merge Assistant ---")
    print(f"User Repo: {source_dir}")
    print(f"Target:    {args.repo}")
    print(f"Branch:    {args.branch}")

    # 1. Check Clean State
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=source_dir):
        print("\n[!] Error: Repo has uncommitted changes. Commit or stash first.")
        sys.exit(1)

    # 2. Safety Check
    current_branch = get_current_branch(source_dir)
    if args.branch == current_branch:
        print(f"\n[!] Error: Cannot use current branch '{current_branch}' as target.")
        sys.exit(1)

    # 3. Add/Update Submodule
    if not submodule_full_path.exists():
        print(f"\n-> Downloading external repo...")
        run_cmd(f"git submodule add --force {args.repo} {submodule_rel_path}", cwd=source_dir)
    else:
        print(f"\n-> Updating external repo...")
        run_cmd(f"git submodule update --init --recursive --remote {submodule_rel_path}", cwd=source_dir)

    # 4. Archive
    print(f"\n-> Creating archive...")
    try:
        run_cmd(f"git archive --format=tar {git_treeish} > {TEMP_TAR}", cwd=submodule_full_path)
    except:
        print(f"[!] Error: Path '{inner_path}' not found in external repo.")
        sys.exit(1)

    # 5. Switch Branch
    print(f"\n-> Switching to branch '{args.branch}'...")
    run_cmd(f"git checkout -B {args.branch}", cwd=source_dir)

    # 6. Clean Configuration
    print("-> Cleaning old config files...")
    for item in source_dir.iterdir():
        if item.name == ".git" or item.name == EXTERNAL_DIR: continue
        if item == script_location or script_location.is_relative_to(item): continue

        if item.name.startswith(CHEZMOI_PREFIXES):
            if item.is_dir(): shutil.rmtree(item)
            else: item.unlink()

    # 7. Import (FIXED: Added --source)
    print("-> Importing via chezmoi...")
    # We force chezmoi to use the current repo as the source
    run_cmd(f"chezmoi import --source {source_dir} --destination {Path.home()} {TEMP_TAR}", cwd=source_dir)

    # 8. Commit & Push
    print("-> Committing and Pushing...")
    run_cmd("git add .", cwd=source_dir)
    run_cmd(f"git commit --allow-empty -m 'Import from {args.repo}'", cwd=source_dir, exit_on_fail=False)
    
    try:
        run_cmd(f"git push -f origin {args.branch}", cwd=source_dir)
        print("\nSUCCESS!")
        print(f"Compare here: https://github.com/YOUR_USER/YOUR_REPO/compare/{args.branch}?expand=1")
    except:
        print("\n[!] Push failed. Set your origin manually.")

    # 9. Reset & Cleanup (FIXED: Force remove .external_sources)
    print(f"\n-> Returning to {current_branch}...")
    run_cmd(f"git checkout {current_branch}", cwd=source_dir)
    
    # Force delete the external sources dir if it was left behind by git
    external_dir_path = source_dir / EXTERNAL_DIR
    if external_dir_path.exists():
        print(f"-> Cleaning up {EXTERNAL_DIR}...")
        shutil.rmtree(external_dir_path)

if __name__ == "__main__":
    main()