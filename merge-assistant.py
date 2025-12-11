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

def run_cmd(cmd, cwd=None, exit_on_fail=True, capture=False):
    try:
        result = subprocess.run(
            cmd, 
            shell=True, 
            check=True, 
            cwd=cwd, 
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None
        )
        if capture:
            return result.stdout.decode().strip()
    except subprocess.CalledProcessError:
        if not capture:
            print(f"\n[!] Error running command: {cmd}")
        if exit_on_fail: sys.exit(1)
        return None

def get_current_branch(cwd):
    return run_cmd("git branch --show-current", cwd=cwd, capture=True)

def get_git_remote_url(cwd):
    url = run_cmd("git remote get-url origin", cwd=cwd, capture=True)
    if not url: return None
    if url.startswith("git@"):
        url = url.replace(":", "/").replace("git@", "https://")
    if url.endswith(".git"):
        url = url[:-4]
    return url

def get_git_root(path):
    try:
        super_root = subprocess.check_output(
            ["git", "rev-parse", "--show-superproject-working-tree"], 
            cwd=path, stderr=subprocess.DEVNULL
        ).decode().strip()
        if super_root: return Path(super_root)
        return Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=path).decode().strip())
    except:
        print("[!] Error: Must be run inside a git repository.")
        sys.exit(1)

def get_submodule_commit(path):
    """Returns the current HEAD commit hash of the submodule."""
    return run_cmd("git rev-parse HEAD", cwd=path, capture=True, exit_on_fail=False)

def get_upstream_diffs(submodule_path, old_commit, new_commit, inner_path):
    """Returns list of files changed between two commits inside the submodule."""
    if not old_commit or not new_commit or old_commit == new_commit:
        return []
    
    # Get list of changed files
    diff_cmd = f"git diff --name-only {old_commit}..{new_commit}"
    output = run_cmd(diff_cmd, cwd=submodule_path, capture=True, exit_on_fail=False)
    
    if not output: return []
    
    files = output.splitlines()
    # Filter by inner_path if specified
    if inner_path and inner_path != ".":
        files = [f for f in files if f.startswith(inner_path)]
        
    return files

def parse_arguments():
    parser = argparse.ArgumentParser(description="Chezmoi Merge Assistant")
    parser.add_argument("--repo", "-r", required=True, help="GitHub URL of dotfiles repo")
    parser.add_argument("--path", "-p", default=".", help="Path inside repo (default: root)")
    parser.add_argument("--branch", "-b", default=DEFAULT_BRANCH, help="Branch name")
    return parser.parse_args()

def show_summary(source_dir, branch_name, upstream_changes):
    print("\n" + "="*60)
    print(f"{'ANALYSIS SUMMARY':^60}")
    print("="*60)
    
    # 1. Show what happened in the External Repo (The "News Feed")
    if upstream_changes:
        print(f"\n[!] FRESH UPSTREAM UPDATES")
        print(f"    (These files changed in the external repo since your last pull)")
        for f in sorted(upstream_changes):
            print(f"    * {f}")
    else:
        print(f"\n[i] UPSTREAM STATUS")
        print(f"    No new changes in external repo (or first run).")

    # 2. Show the Net Result on your config
    changes = run_cmd(f"git diff --name-status HEAD..{branch_name}", cwd=source_dir, capture=True)
    
    if not changes:
        print("\n[i] RESULT: No changes to your configuration.")
        return

    added, modified, deleted = [], [], []
    for line in changes.split('\n'):
        if not line.strip(): continue
        parts = line.split(maxsplit=1)
        if len(parts) < 2: continue
        status, filename = parts[0], parts[1]
        
        if status.startswith('A'): added.append(filename)
        elif status.startswith('M'): modified.append(filename)
        elif status.startswith('D'): deleted.append(filename)

    print(f"\n[!] PULL REQUEST PREVIEW")
    print(f"    (Merging the PR will affect these files in your config)")
    
    if added:
        print(f"\n    [+] NEW FILES (You don't have these yet):")
        for f in sorted(added): print(f"        {f}")
        
    if modified:
        print(f"\n    [*] MODIFIED FILES (Content differs):")
        for f in sorted(modified): print(f"        {f}")

    if deleted:
        print(f"\n    [-] DELETED FILES (You have these, upstream doesn't):")
        if len(deleted) > 10:
            print(f"        ({len(deleted)} files... usually your custom scripts)")
        else:
            for f in sorted(deleted): print(f"        {f}")

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
    print(f"Target: {args.repo}")
    print(f"Branch: {args.branch}")

    if subprocess.check_output(["git", "status", "--porcelain"], cwd=source_dir):
        print("\n[!] Error: Repo has uncommitted changes. Commit or stash first.")
        sys.exit(1)

    current_branch = get_current_branch(source_dir)
    if args.branch == current_branch:
        print(f"\n[!] Error: Cannot use current branch '{current_branch}' as target.")
        sys.exit(1)

    # --- SUBMODULE LOGIC (With State Capture) ---
    old_commit = None
    if submodule_full_path.exists():
        old_commit = get_submodule_commit(submodule_full_path)
    else:
        print(f"\n-> Downloading external repo...")
        run_cmd(f"git submodule add --force {args.repo} {submodule_rel_path}", cwd=source_dir)

    print(f"-> Updating external repo...")
    # Update to latest remote
    run_cmd(f"git submodule update --init --recursive --remote {submodule_rel_path}", cwd=source_dir)
    
    new_commit = get_submodule_commit(submodule_full_path)
    
    # Calculate what changed upstream
    upstream_changes = get_upstream_diffs(submodule_full_path, old_commit, new_commit, inner_path)
    # ---------------------------------------------

    print(f"-> Creating archive...")
    try:
        run_cmd(f"git archive --format=tar {git_treeish} > {TEMP_TAR}", cwd=submodule_full_path)
    except:
        print(f"[!] Error: Path '{inner_path}' not found in external repo.")
        sys.exit(1)

    print(f"-> Switching to branch '{args.branch}'...")
    run_cmd(f"git checkout -B {args.branch}", cwd=source_dir)

    print("-> Cleaning old config files...")
    for item in source_dir.iterdir():
        if item.name == ".git" or item.name == EXTERNAL_DIR: continue
        if item == script_location or script_location.is_relative_to(item): continue

        if item.name.startswith(CHEZMOI_PREFIXES):
            if item.is_dir(): shutil.rmtree(item)
            else: item.unlink()

    print("-> Importing via chezmoi...")
    run_cmd(f"chezmoi import --source {source_dir} --destination {Path.home()} {TEMP_TAR}", cwd=source_dir)

    print("-> Committing and Pushing...")
    run_cmd("git add .", cwd=source_dir)
    run_cmd(f"git commit --allow-empty -m 'Import from {args.repo}'", cwd=source_dir, exit_on_fail=False)
    
    push_success = False
    try:
        run_cmd(f"git push -f origin {args.branch}", cwd=source_dir)
        push_success = True
    except:
        print("\n[!] Push failed. Set your origin manually.")

    print(f"-> Returning to {current_branch}...")
    run_cmd(f"git checkout {current_branch}", cwd=source_dir)
    
    external_dir_path = source_dir / EXTERNAL_DIR
    if external_dir_path.exists():
        shutil.rmtree(external_dir_path, ignore_errors=True)

    # --- SUMMARY DISPLAY ---
    if push_success:
        remote_url = get_git_remote_url(source_dir)
        if remote_url:
            print("\n" + "="*60)
            print(f"SUCCESS! Compare here: {remote_url}/compare/{args.branch}?expand=1")
    
    show_summary(source_dir, args.branch, upstream_changes)

if __name__ == "__main__":
    main()