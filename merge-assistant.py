#!/usr/bin/env python3
import sys
import shutil
import argparse
import subprocess
from pathlib import Path

# Local imports
import config
import utils
import merger

def parse_arguments():
    parser = argparse.ArgumentParser(description="Chezmoi Merge Assistant")
    parser.add_argument("--repo", "-r", required=True, help="GitHub URL of dotfiles repo")
    parser.add_argument("--path", "-p", default=".", help="Path inside repo (default: root)")
    parser.add_argument("--branch", "-b", default=config.DEFAULT_BRANCH, help="Branch name")
    return parser.parse_args()

def main():
    args = parse_arguments()
    inner_path = args.path.strip("/")
    git_treeish = "HEAD" if inner_path in ["", "."] else f"HEAD:{inner_path}"

    script_location = Path(__file__).parent.resolve()
    source_dir = utils.get_git_root(script_location)
    
    repo_name = args.repo.split("/")[-1].replace(".git", "")
    cache_dir = source_dir / config.EXTERNAL_DIR
    target_repo_path = cache_dir / repo_name

    print(f"--- Chezmoi Merge Assistant ---")
    print(f"Target: {args.repo}")
    print(f"Branch: {args.branch}")

    if subprocess.check_output(["git", "status", "--porcelain"], cwd=source_dir):
        print("\n[!] Error: Repo has uncommitted changes. Commit or stash first.")
        sys.exit(1)

    if not cache_dir.exists(): cache_dir.mkdir()

    old_commit = None
    if target_repo_path.exists():
        old_commit = utils.get_commit_hash(target_repo_path)
        print(f"-> Updating external repo cache...")
        utils.run_cmd("git fetch origin", cwd=target_repo_path)
        utils.run_cmd("git reset --hard origin/HEAD", cwd=target_repo_path)
    else:
        print(f"-> Cloning external repo to cache...")
        utils.run_cmd(f"git clone {args.repo} {repo_name}", cwd=cache_dir)
    
    new_commit = utils.get_commit_hash(target_repo_path)
    upstream_changes = utils.get_upstream_diffs(target_repo_path, old_commit, new_commit, inner_path)

    print(f"-> Creating archive...")
    try:
        utils.run_cmd(f"git archive --format=tar {git_treeish} > {config.TEMP_TAR}", cwd=target_repo_path)
    except:
        print(f"[!] Error: Path '{inner_path}' not found in external repo.")
        sys.exit(1)

    print(f"-> Switching to branch '{args.branch}'...")
    utils.run_cmd(f"git checkout -B {args.branch}", cwd=source_dir)

    print("-> Cleaning old config files...")
    for item in source_dir.iterdir():
        if item.name == ".git" or item.name == config.EXTERNAL_DIR: continue
        if item == script_location or script_location.is_relative_to(item): continue
        if item.name.startswith(config.CHEZMOI_PREFIXES):
            if item.is_dir(): shutil.rmtree(item)
            else: item.unlink()

    print("-> Importing via chezmoi...")
    utils.run_cmd(f"chezmoi import --source {source_dir} --destination {Path.home()} {config.TEMP_TAR}", cwd=source_dir)

    print("-> Committing and Pushing...")
    utils.run_cmd("git add .", cwd=source_dir)
    utils.run_cmd(f"git commit --allow-empty -m 'Import from {args.repo}'", cwd=source_dir, exit_on_fail=False)
    try:
        utils.run_cmd(f"git push -f origin {args.branch}", cwd=source_dir)
    except:
        pass

    current_branch = utils.get_current_branch(source_dir)
    print(f"-> Returning to {current_branch}...")
    utils.run_cmd(f"git checkout -", cwd=source_dir)
    
    merger.show_summary(source_dir, args.branch, upstream_changes, inner_path)

    if upstream_changes:
        print(f"\n-> Found {len(upstream_changes)} files changed upstream.")
        print(f"   Would you like to run the Smart Merge wizard? (y/n)")
        if input("   > ").strip().lower() == 'y':
            merger.smart_merge(source_dir, target_repo_path, args.branch, upstream_changes, old_commit, new_commit, inner_path)

if __name__ == "__main__":
    main()