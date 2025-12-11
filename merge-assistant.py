#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
import argparse
import re
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
    except subprocess.CalledProcessError as e:
        if not capture:
            print(f"\n[!] Error running command: {cmd}")
        if exit_on_fail: sys.exit(1)
        return None

def get_current_branch(cwd):
    return run_cmd("git branch --show-current", cwd=cwd, capture=True)

def get_git_remote_url(cwd):
    """Gets the origin remote URL to generate the PR link."""
    url = run_cmd("git remote get-url origin", cwd=cwd, capture=True)
    if not url: return None
    
    # Convert SSH (git@github.com:User/Repo.git) to HTTPS (https://github.com/User/Repo)
    if url.startswith("git@"):
        url = url.replace(":", "/").replace("git@", "https://")
    if url.endswith(".git"):
        url = url[:-4]
    return url

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

def show_summary(source_dir, branch_name):
    """Analyzes the changes between the previous branch and the comparison branch."""
    print("\n" + "="*40)
    print("       COMPARISON SUMMARY")
    print("="*40)
    
    # We are currently on the previous branch (e.g. main). 
    # We want to see what 'branch_name' has that we don't, or what is different.
    
    # Get the list of changed files
    # --name-status gives us: 'M file', 'A file', 'D file'
    # We compare HEAD (main) vs branch_name
    changes = run_cmd(f"git diff --name-status HEAD..{branch_name}", cwd=source_dir, capture=True)
    
    if not changes:
        print("No changes detected.")
        return

    added = []
    modified = []
    deleted = []

    for line in changes.split('\n'):
        if not line.strip(): continue
        parts = line.split(maxsplit=1)
        if len(parts) < 2: continue
        
        status, filename = parts[0], parts[1]
        
        # In git diff HEAD..BRANCH:
        # A (Added) means the BRANCH has it, HEAD doesn't. (New upstream file)
        # D (Deleted) means HEAD has it, BRANCH doesn't. (You have a file they don't)
        # M (Modified) means both have it, but content differs.
        
        if status.startswith('A'): added.append(filename)
        elif status.startswith('M'): modified.append(filename)
        elif status.startswith('D'): deleted.append(filename)

    if added:
        print(f"\n[+] NEW FILES (Upstream has these, you don't):")
        for f in sorted(added): print(f"    {f}")
        
    if modified:
        print(f"\n[*] MODIFIED FILES (Content differs):")
        for f in sorted(modified): print(f"    {f}")

    if deleted:
        print(f"\n[-] DELETED FILES (You have these, upstream doesn't):")
        # Optional: Print only the first few if there are many
        if len(deleted) > 10:
            print(f"    ({len(deleted)} files... usually your custom scripts or private keys)")
        else:
            for f in sorted(deleted): print(f"    {f}")

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

    # 7. Import
    print("-> Importing via chezmoi...")
    run_cmd(f"chezmoi import --source {source_dir} --destination {Path.home()} {TEMP_TAR}", cwd=source_dir)

    # 8. Commit & Push
    print("-> Committing and Pushing...")
    run_cmd("git add .", cwd=source_dir)
    run_cmd(f"git commit --allow-empty -m 'Import from {args.repo}'", cwd=source_dir, exit_on_fail=False)
    
    push_success = False
    try:
        run_cmd(f"git push -f origin {args.branch}", cwd=source_dir)
        push_success = True
    except:
        print("\n[!] Push failed. Set your origin manually.")

    # 9. Reset & Cleanup
    print(f"\n-> Returning to {current_branch}...")
    run_cmd(f"git checkout {current_branch}", cwd=source_dir)
    
    external_dir_path = source_dir / EXTERNAL_DIR
    if external_dir_path.exists():
        # Clean up safely
        shutil.rmtree(external_dir_path, ignore_errors=True)

    # 10. Summary & Links
    if push_success:
        remote_url = get_git_remote_url(source_dir)
        if remote_url:
            print("\nSUCCESS!")
            print(f"Compare here: {remote_url}/compare/{args.branch}?expand=1")
    
    # Show the file analysis
    show_summary(source_dir, args.branch)

if __name__ == "__main__":
    main()