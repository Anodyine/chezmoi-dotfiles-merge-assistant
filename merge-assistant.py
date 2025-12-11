#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
import argparse
import tempfile
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

def run_cmd(cmd, cwd=None, exit_on_fail=True, capture=False, binary=False):
    """
    Runs a command. 
    If capture=True, returns stdout (String by default, Bytes if binary=True).
    """
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
            return result.stdout if binary else result.stdout.decode('utf-8', errors='replace').strip()
    except subprocess.CalledProcessError:
        if not capture and exit_on_fail:
            print(f"\n[!] Error running command: {cmd}")
            sys.exit(1)
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
    return run_cmd("git rev-parse HEAD", cwd=path, capture=True, exit_on_fail=False)

def get_upstream_diffs(repo_path, old_commit, new_commit, inner_path):
    if not old_commit or not new_commit or old_commit == new_commit:
        return []
    # name-only is safe for file lists
    diff_cmd = f"git diff --name-only {old_commit}..{new_commit}"
    output = run_cmd(diff_cmd, cwd=repo_path, capture=True, exit_on_fail=False)
    if not output: return []
    files = output.splitlines()
    if inner_path and inner_path != ".":
        files = [f for f in files if f.startswith(inner_path)]
    return files

def get_file_content_at_commit(repo_path, commit, filepath):
    """Reads a file from a specific git commit as BYTES to handle binaries."""
    try:
        return run_cmd(f"git show {commit}:{filepath}", cwd=repo_path, capture=True, exit_on_fail=False, binary=True)
    except:
        return None

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

def find_local_match(source_dir, upstream_file, inner_path):
    """Finds the corresponding local chezmoi file for an upstream path."""
    clean = clean_upstream_path(upstream_file, inner_path)
    for item in source_dir.rglob("*"):
        if item.is_file() and ".git" not in item.parts:
            rel_path = item.relative_to(source_dir)
            norm = normalize_chezmoi_path(str(rel_path))
            if norm.endswith(clean):
                return str(rel_path)
    return None

def is_binary(content):
    """Simple heuristic to detect binary content (contains null byte)."""
    return b'\0' in content if content else False

def show_summary(source_dir, branch_name, upstream_changes, inner_path):
    print("\n" + "="*60)
    print(f"{'ANALYSIS SUMMARY':^60}")
    print("="*60)
    
    if upstream_changes:
        print(f"\n[!] FRESH UPSTREAM UPDATES")
        print(f"    (These files changed in the external repo since your last pull)")
        for f in sorted(upstream_changes):
            print(f"    * {f}")
    else:
        print(f"\n[i] UPSTREAM STATUS")
        print(f"    No new changes in external repo (or first run).")

    changes = run_cmd(f"git diff --name-status HEAD..{branch_name}", cwd=source_dir, capture=True)
    added, modified = [], []
    if changes:
        for line in changes.split('\n'):
            if not line.strip(): continue
            parts = line.split(maxsplit=1)
            if len(parts) < 2: continue
            status, filename = parts[0], parts[1]
            if status.startswith('A'): added.append(filename)
            elif status.startswith('M'): modified.append(filename)

    collisions = []
    if upstream_changes and modified:
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
            print("*"*60)
            for f in sorted(collisions):
                print(f"    !! {f}")
    
    remote_url = get_git_remote_url(source_dir)
    if remote_url:
        print("\n" + "="*60)
        print(f"COMPARE HERE: {remote_url}/compare/{branch_name}?expand=1")
        print("="*60 + "\n")
    
    return added, modified

def smart_merge(source_dir, cache_dir, branch_name, upstream_changes, old_commit, new_commit, inner_path):
    if not upstream_changes: return

    print(f"-> Starting Smart Merge for {len(upstream_changes)} updated files...")
    
    processed_count = 0
    conflict_count = 0

    for upstream_file in upstream_changes:
        local_file = find_local_match(source_dir, upstream_file, inner_path)
        
        if not local_file:
            continue
            
        full_local_path = source_dir / local_file
        
        # 1. Get Base Content (Old Upstream) - Bytes
        base_content = get_file_content_at_commit(cache_dir / upstream_file.split('/')[0], old_commit, upstream_file)
        
        # 2. Get Their Content (New Upstream) - Bytes
        # Note: git show <branch>:<file>
        try:
            theirs_content = run_cmd(f"git show {branch_name}:{local_file}", cwd=source_dir, capture=True, exit_on_fail=False, binary=True)
        except:
            theirs_content = None

        # 3. Get Your Content (Local File) - Bytes
        try:
            with open(full_local_path, 'rb') as f:
                yours_content = f.read()
        except:
            yours_content = None

        if base_content is None or theirs_content is None or yours_content is None:
            continue

        # --- LOGIC GATES ---

        # Binary Safety Check
        if is_binary(base_content) or is_binary(yours_content) or is_binary(theirs_content):
             # For binaries, strict equality check
            if yours_content == base_content:
                print(f"    [Auto-Update] {local_file} (Binary)")
                run_cmd(f"git checkout {branch_name} -- {local_file}", cwd=source_dir)
                processed_count += 1
            else:
                print(f"\n    [!] CONFLICT: {local_file} (Binary)")
                print("        [t]ake theirs")
                print("        [k]eep yours")
                if input("        Select action [t/k]: ").strip().lower() == 't':
                    run_cmd(f"git checkout {branch_name} -- {local_file}", cwd=source_dir)
                    processed_count += 1
            continue

        # Text Logic
        # Case A: You haven't touched it (Yours == Base)
        # We strip whitespace to avoid false conflicts on line endings
        if yours_content.strip() == base_content.strip():
            print(f"    [Auto-Update] {local_file}")
            run_cmd(f"git checkout {branch_name} -- {local_file}", cwd=source_dir)
            processed_count += 1
            continue

        # Case B: Conflict
        print(f"\n    [!] CONFLICT: {local_file}")
        print("        (Local changes detected)")
        print("        [t]ake theirs (discard your changes)")
        print("        [k]eep yours (discard upstream update)")
        print("        [m]erge (try auto-merge)")
        
        while True:
            choice = input("        Select action [t/k/m]: ").strip().lower()
            
            if choice == 'k':
                print("        -> Keeping local version.")
                break
            
            elif choice == 't':
                print("        -> Overwriting with upstream.")
                run_cmd(f"git checkout {branch_name} -- {local_file}", cwd=source_dir)
                processed_count += 1
                break
            
            elif choice == 'm':
                print("        -> Attempting 3-way merge...")
                
                with tempfile.NamedTemporaryFile(mode='wb', delete=False) as f_base, \
                     tempfile.NamedTemporaryFile(mode='wb', delete=False) as f_theirs:
                    
                    f_base.write(base_content)
                    f_theirs.write(theirs_content)
                    f_base_path = f_base.name
                    f_theirs_path = f_theirs.name

                # Run git merge-file
                # Return code 0 = Success (clean auto-merge)
                # Return code >0 = Conflicts (markers added)
                ret_code = 0
                try:
                    proc = subprocess.run(
                        ["git", "merge-file", "-L", "current", "-L", "base", "-L", "incoming", str(full_local_path), f_base_path, f_theirs_path],
                        cwd=source_dir
                    )
                    ret_code = proc.returncode
                except:
                    print("        [!] Merge tool failed.")
                
                # Cleanup temps
                os.remove(f_base_path)
                os.remove(f_theirs_path)

                if ret_code == 0:
                    print("        ✅ Auto-merge successful! (No markers needed)")
                    # No editor needed, file is updated in place
                else:
                    print("        ⚠️  Conflict markers added (<<<<). Please resolve manually.")
                    editor = os.environ.get('EDITOR', 'nano')
                    subprocess.call([editor, str(full_local_path)])
                
                processed_count += 1
                conflict_count += 1
                break

    print(f"\n✅ Smart Merge Complete. Updated {processed_count} files.")
    
    print("\n-> Would you like to see the final 'chezmoi diff' (Source vs Home)? (y/n)")
    if input("   > ").strip().lower() == 'y':
        subprocess.run("chezmoi diff", shell=True, cwd=source_dir)

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
    cache_dir = source_dir / EXTERNAL_DIR
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
        old_commit = get_commit_hash(target_repo_path)
        print(f"-> Updating external repo cache...")
        run_cmd("git fetch origin", cwd=target_repo_path)
        run_cmd("git reset --hard origin/HEAD", cwd=target_repo_path)
    else:
        print(f"-> Cloning external repo to cache...")
        run_cmd(f"git clone {args.repo} {repo_name}", cwd=cache_dir)
    
    new_commit = get_commit_hash(target_repo_path)
    upstream_changes = get_upstream_diffs(target_repo_path, old_commit, new_commit, inner_path)

    print(f"-> Creating archive...")
    try:
        run_cmd(f"git archive --format=tar {git_treeish} > {TEMP_TAR}", cwd=target_repo_path)
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
    try:
        run_cmd(f"git push -f origin {args.branch}", cwd=source_dir)
    except:
        pass

    current_branch = get_current_branch(source_dir)
    print(f"-> Returning to {current_branch}...")
    run_cmd(f"git checkout -", cwd=source_dir) # Go back to original branch
    
    # Show analysis
    added, modified = show_summary(source_dir, args.branch, upstream_changes, inner_path)

    # Prompt for Smart Merge
    if upstream_changes:
        print(f"\n-> Found {len(upstream_changes)} files changed upstream.")
        print(f"   Would you like to run the Smart Merge wizard? (y/n)")
        if input("   > ").strip().lower() == 'y':
            smart_merge(source_dir, target_repo_path, args.branch, upstream_changes, old_commit, new_commit, inner_path)

if __name__ == "__main__":
    main()