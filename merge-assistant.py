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

def get_commit_hash(path):
    """Returns the current HEAD commit hash of a repo."""
    return run_cmd("git rev-parse HEAD", cwd=path, capture=True, exit_on_fail=False)

def get_upstream_diffs(repo_path, old_commit, new_commit, inner_path):
    """Returns list of files changed between two commits."""
    if not old_commit or not new_commit or old_commit == new_commit:
        return []
    
    diff_cmd = f"git diff --name-only {old_commit}..{new_commit}"
    output = run_cmd(diff_cmd, cwd=repo_path, capture=True, exit_on_fail=False)
    
    if not output: return []
    
    files = output.splitlines()
    if inner_path and inner_path != ".":
        files = [f for f in files if f.startswith(inner_path)]
        
    return files

def normalize_chezmoi_path(path):
    p = path.replace("dot_", ".")
    p = p.replace("private_", "")
    p = p.replace("executable_", "")
    p = p.replace("exact_", "")
    p = p.replace("readonly_", "")
    return p

def clean_upstream_path(path, inner_path):
    if inner_path and inner_path != "." and path.startswith(inner_path):
        return path[len(inner_path):].lstrip("/")
    return path

def show_summary(source_dir, branch_name, upstream_changes, inner_path):
    print("\n" + "="*60)
    print(f"{'ANALYSIS SUMMARY':^60}")
    print("="*60)
    
    # 1. UPSTREAM NEWS
    if upstream_changes:
        print(f"\n[!] FRESH UPSTREAM UPDATES")
        print(f"    (These files changed in the external repo since your last pull)")
        for f in sorted(upstream_changes):
            print(f"    * {f}")
    else:
        print(f"\n[i] UPSTREAM STATUS")
        print(f"    No new changes in external repo (or first run).")

    # 2. PR PREVIEW
    changes = run_cmd(f"git diff --name-status HEAD..{branch_name}", cwd=source_dir, capture=True)
    
    added, modified, deleted = [], [], []
    if changes:
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

    # 3. COLLISION DETECTION
    if upstream_changes and modified:
        collisions = []
        clean_upstream = [clean_upstream_path(f, inner_path) for f in upstream_changes]
        for mod_file in modified:
            norm_mod = normalize_chezmoi_path(mod_file)
            for up_file in clean_upstream:
                if norm_mod.endswith(up_file) or up_file.endswith(norm_mod):
                    collisions.append(mod_file)
                    break
        
        if collisions:
            print("\n" + "*"*60)
            print("   ATTENTION REQUIRED: MODIFIED LOCALLY & UPDATED UPSTREAM")
            print("   (You customized these files, and the author just updated them too)")
            print("*"*60)
            for f in sorted(collisions):
                print(f"    !! {f}")
    
    remote_url = get_git_remote_url(source_dir)
    if remote_url:
        print("\n" + "="*60)
        print(f"COMPARE HERE: {remote_url}/compare/{branch_name}?expand=1")
        print("="*60 + "\n")

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
    
    # We clone into .external_sources/repo_name
    repo_name = args.repo.split("/")[-1].replace(".git", "")
    cache_dir = source_dir / EXTERNAL_DIR
    target_repo_path = cache_dir / repo_name

    print(f"--- Chezmoi Merge Assistant ---")
    print(f"Target: {args.repo}")
    print(f"Branch: {args.branch}")

    # 1. Check Clean State (ignoring untracked files in .external_sources if ignored)
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=source_dir):
        print("\n[!] Error: Repo has uncommitted changes. Commit or stash first.")
        # Tip for the user
        print(f"    (Make sure '{EXTERNAL_DIR}/' is in your .gitignore)")
        sys.exit(1)

    current_branch = get_current_branch(source_dir)
    if args.branch == current_branch:
        print(f"\n[!] Error: Cannot use current branch '{current_branch}' as target.")
        sys.exit(1)

    # 2. CACHE MANAGEMENT (Clone/Update)
    if not cache_dir.exists():
        cache_dir.mkdir()

    old_commit = None
    if target_repo_path.exists():
        old_commit = get_commit_hash(target_repo_path)
        print(f"-> Updating external repo cache...")
        # Reset to ensure clean state for pull
        run_cmd("git fetch origin", cwd=target_repo_path)
        run_cmd("git reset --hard origin/HEAD", cwd=target_repo_path)
    else:
        print(f"-> Cloning external repo to cache...")
        run_cmd(f"git clone {args.repo} {repo_name}", cwd=cache_dir)
    
    new_commit = get_commit_hash(target_repo_path)
    upstream_changes = get_upstream_diffs(target_repo_path, old_commit, new_commit, inner_path)

    # 3. ARCHIVE
    print(f"-> Creating archive...")
    try:
        run_cmd(f"git archive --format=tar {git_treeish} > {TEMP_TAR}", cwd=target_repo_path)
    except:
        print(f"[!] Error: Path '{inner_path}' not found in external repo.")
        sys.exit(1)

    # 4. BRANCH & CLEAN
    print(f"-> Switching to branch '{args.branch}'...")
    run_cmd(f"git checkout -B {args.branch}", cwd=source_dir)

    print("-> Cleaning old config files...")
    for item in source_dir.iterdir():
        if item.name == ".git" or item.name == EXTERNAL_DIR: continue
        if item == script_location or script_location.is_relative_to(item): continue

        if item.name.startswith(CHEZMOI_PREFIXES):
            if item.is_dir(): shutil.rmtree(item)
            else: item.unlink()

    # 5. IMPORT
    print("-> Importing via chezmoi...")
    run_cmd(f"chezmoi import --source {source_dir} --destination {Path.home()} {TEMP_TAR}", cwd=source_dir)

    # 6. PUSH
    print("-> Committing and Pushing...")
    run_cmd("git add .", cwd=source_dir)
    run_cmd(f"git commit --allow-empty -m 'Import from {args.repo}'", cwd=source_dir, exit_on_fail=False)
    
    try:
        run_cmd(f"git push -f origin {args.branch}", cwd=source_dir)
    except:
        print("\n[!] Push failed. Set your origin manually.")

    # 7. RESET
    print(f"-> Returning to {current_branch}...")
    run_cmd(f"git checkout {current_branch}", cwd=source_dir)
    
    # WE DO NOT DELETE EXTERNAL_DIR HERE. We leave it for the "News Feed" next time.
    
    show_summary(source_dir, args.branch, upstream_changes, inner_path)

if __name__ == "__main__":
    main()