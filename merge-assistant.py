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

# We only delete items that explicitly look like Chezmoi config objects.
CHEZMOI_PREFIXES = (
    "dot_", 
    "private_", 
    "executable_", 
    "exact_", 
    "symlink_", 
    "modify_", 
    "create_", 
    "empty_",
    "readonly_"
)

def run_cmd(cmd, cwd=None, exit_on_fail=True):
    """Executes a shell command."""
    try:
        subprocess.run(cmd, shell=True, check=True, cwd=cwd)
    except subprocess.CalledProcessError:
        print(f"\n[!] Error running command: {cmd}")
        if exit_on_fail:
            sys.exit(1)

def get_current_branch(cwd):
    return subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=cwd
    ).decode().strip()

def get_git_root(path):
    """Finds the root of the git repo containing the given path."""
    try:
        # Check if inside a submodule (returns parent repo root)
        super_root = subprocess.check_output(
            ["git", "rev-parse", "--show-superproject-working-tree"], 
            cwd=path, stderr=subprocess.DEVNULL
        ).decode().strip()
        
        if super_root:
            return Path(super_root)
            
        # Normal repo root
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], 
            cwd=path
        ).decode().strip()
        return Path(root)

    except subprocess.CalledProcessError:
        print("[!] Error: This script must be run inside a git repository.")
        sys.exit(1)

def parse_arguments():
    parser = argparse.ArgumentParser(description="Chezmoi Merge Assistant: Import external dotfiles into a comparison branch.")
    
    parser.add_argument(
        "--repo", "-r", 
        required=True, 
        help="The GitHub URL of the dotfiles repo (e.g. https://github.com/user/dots.git)"
    )
    
    parser.add_argument(
        "--path", "-p", 
        default=".", 
        help="The path inside the repo where dotfiles live (default: root)"
    )
    
    parser.add_argument(
        "--branch", "-b", 
        default=DEFAULT_BRANCH, 
        help=f"The name of the local branch to create for comparison (default: {DEFAULT_BRANCH})"
    )

    return parser.parse_args()

def main():
    args = parse_arguments()
    
    # Normalize path
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
    print(f"Sub-path:  {inner_path if inner_path else '(root)'}")
    print(f"Branch:    {args.branch}")

    # 1. Check Clean State
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=source_dir)
    if status:
        print("\n[!] Error: Your dotfiles repo has uncommitted changes.")
        print("    Please commit or stash them before running this tool.")
        sys.exit(1)

    # 2. Safety Check: Don't overwrite current branch
    current_branch = get_current_branch(source_dir)
    if args.branch == current_branch:
        print(f"\n[!] Error: You cannot use the current branch ('{current_branch}') as the comparison target.")
        print("    Please specify a different branch name using --branch.")
        sys.exit(1)

    # 3. Add/Update External Submodule
    if not submodule_full_path.exists():
        print(f"\n-> Downloading external repo to {submodule_rel_path}...")
        run_cmd(f"git submodule add --force {args.repo} {submodule_rel_path}", cwd=source_dir)
    else:
        print(f"\n-> Updating external repo...")
        run_cmd(f"git submodule update --init --recursive --remote {submodule_rel_path}", cwd=source_dir)

    # 4. Archive
    print(f"\n-> Creating archive of '{inner_path}'...")
    try:
        run_cmd(f"git archive --format=tar {git_treeish} > {TEMP_TAR}", cwd=submodule_full_path)
    except SystemExit:
        print(f"[!] Error: Path '{inner_path}' not found in external repo.")
        sys.exit(1)

    # 5. Switch Branch
    print(f"\n-> Switching to comparison branch '{args.branch}'...")
    run_cmd(f"git checkout -B {args.branch}", cwd=source_dir)

    # 6. Clean Configuration (Safely)
    print("-> Cleaning old config files (preserving non-config dirs/files)...")
    
    for item in source_dir.iterdir():
        # --- PROTECTED ITEMS ---
        if item.name == ".git": continue
        if item.name == EXTERNAL_DIR: continue
        # Protect the tool itself
        if item == script_location or script_location.is_relative_to(item):
            continue

        # --- DELETION LOGIC ---
        if item.name.startswith(CHEZMOI_PREFIXES):
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        else:
            print(f"   Skipping (Preserved): {item.name}")

    # 7. Import
    print("-> Importing via chezmoi...")
    run_cmd(f"chezmoi import --destination {Path.home()} {TEMP_TAR}", cwd=source_dir)

    # 8. Commit & Push
    print("-> Committing and Pushing...")
    run_cmd("git add .", cwd=source_dir)
    run_cmd(f"git commit --allow-empty -m 'Import external dots from {args.repo}'", cwd=source_dir, exit_on_fail=False)
    
    try:
        run_cmd(f"git push -f origin {args.branch}", cwd=source_dir)
        print("\nSUCCESS!")
        print(f"Compare here: https://github.com/YOUR_USER/YOUR_REPO/compare/{args.branch}?expand=1")
    except SystemExit:
        print("\n[!] Push failed. You may need to set your origin manually.")

    # 9. Reset
    print(f"\n-> Returning to previous branch ({current_branch})...")
    run_cmd(f"git checkout {current_branch}", cwd=source_dir)

if __name__ == "__main__":
    main()