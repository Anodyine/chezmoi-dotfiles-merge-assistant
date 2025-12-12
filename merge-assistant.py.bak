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

CHEZMOI_PREFIXES = (
    "dot_", "private_", "executable_", "exact_", "symlink_", 
    "modify_", "create_", "empty_", "readonly_"
)

def run_cmd(cmd, cwd=None, exit_on_fail=True, capture=False, binary=False):
    """
    Runs a command. Handles both string (shell=True) and list (shell=False) inputs.
    """
    use_shell = isinstance(cmd, str)
    try:
        result = subprocess.run(
            cmd, 
            shell=use_shell, 
            check=True, 
            cwd=cwd, 
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None
        )
        if capture:
            return result.stdout if binary else result.stdout.decode('utf-8', errors='replace').strip()
    except subprocess.CalledProcessError:
        if not capture and exit_on_fail:
            cmd_str = cmd if use_shell else " ".join(cmd)
            print(f"\n[!] Error running command: {cmd_str}")
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
    diff_cmd = f"git diff --name-only {old_commit}..{new_commit}"
    output = run_cmd(diff_cmd, cwd=repo_path, capture=True, exit_on_fail=False)
    if not output: return []
    files = output.splitlines()
    if inner_path and inner_path != ".":
        files = [f for f in files if f.startswith(inner_path)]
    return files

def get_file_content_at_commit(repo_path, commit, filepath):
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
    clean = clean_upstream_path(upstream_file, inner_path)
    for item in source_dir.rglob("*"):
        if item.is_file() and ".git" not in item.parts:
            rel_path = item.relative_to(source_dir)
            norm = normalize_chezmoi_path(str(rel_path))
            if norm.endswith(clean):
                return str(rel_path)
    return None

def is_binary(content):
    return b'\0' in content if content else False

def print_diff(label, content_a, content_b):
    print(f"\n--- {label} ---")
    try:
        a_str = content_a.decode('utf-8').splitlines(keepends=True)
        b_str = content_b.decode('utf-8').splitlines(keepends=True)
        import difflib
        diff = difflib.unified_diff(a_str, b_str, fromfile="Base", tofile="New", n=0)
        has_output = False
        for line in diff:
            has_output = True
            if line.startswith('+'): print(f"\033[32m{line.strip()}\033[0m")
            elif line.startswith('-'): print(f"\033[31m{line.strip()}\033[0m")
            elif line.startswith('@'): print(f"\033[36m{line.strip()}\033[0m")
        if not has_output: print("(No text changes detected)")
    except:
        print("(Diff unavailable - encoding issue)")

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

def smart_merge(source_dir, cache_dir, branch_name, upstream_changes, old_commit, new_commit, inner_path):
    if not upstream_changes: return

    auto_merge_list = []
    conflict_list = []

    print("-> Analyzing changes...")
    for upstream_file in upstream_changes:
        local_file = find_local_match(source_dir, upstream_file, inner_path)
        if not local_file: continue
        
        full_local_path = source_dir / local_file
        
        # 1. Base (Old Upstream)
        base_content = get_file_content_at_commit(cache_dir / upstream_file.split('/')[0], old_commit, upstream_file)
        # 2. Yours (Local)
        try:
            with open(full_local_path, 'rb') as f: yours_content = f.read()
        except: yours_content = None
        # 3. Theirs (New Upstream)
        try:
            theirs_content = run_cmd(f"git show {branch_name}:{local_file}", cwd=source_dir, capture=True, exit_on_fail=False, binary=True)
        except: theirs_content = None

        if base_content is None or yours_content is None or theirs_content is None: continue

        is_bin = is_binary(base_content) or is_binary(yours_content) or is_binary(theirs_content)

        if not is_bin:
            # Match stripped content to avoid whitespace conflicts
            yours_strip = yours_content.strip()
            base_strip = base_content.strip()
            theirs_strip = theirs_content.strip()
            
            if yours_strip == theirs_strip:
                print(f"    [Skipped] {local_file} (Already up to date)")
                continue
            elif yours_strip == base_strip:
                auto_merge_list.append((local_file, upstream_file))
            else:
                conflict_list.append({'local': local_file, 'base': base_content, 'yours': yours_content, 'theirs': theirs_content, 'is_bin': False})
        else:
            # Binary strict check
            if yours_content == theirs_content:
                print(f"    [Skipped] {local_file} (Already up to date)")
                continue
            elif yours_content == base_content:
                auto_merge_list.append((local_file, upstream_file))
            else:
                conflict_list.append({'local': local_file, 'base': base_content, 'yours': yours_content, 'theirs': theirs_content, 'is_bin': True})

    # ACTION: Auto-Updates
    if auto_merge_list:
        print(f"\n-> Automatically updating {len(auto_merge_list)} files from upstream...")
        files_to_checkout = [x[0] for x in auto_merge_list]
        # FIX: Pass as list to avoid shell injection and git error
        run_cmd(["git", "checkout", branch_name, "--"] + files_to_checkout, cwd=source_dir)
        for f, _ in auto_merge_list:
            print(f"    [Updated] {f}")

    # ACTION: Conflicts
    if not conflict_list:
        print("\n✅ All upstream changes processed successfully!")
        return

    print(f"\n-> Found {len(conflict_list)} files with conflicts.")
    print("   Would you like to resolve them now? (y/n)")
    if input("   > ").strip().lower() != 'y':
        return

    processed = 0
    for item in conflict_list:
        local_file = item['local']
        print("\n" + "*"*60)
        print(f"CONFLICT: {local_file}")
        print("*"*60)

        if not item['is_bin']:
            print_diff("YOUR CHANGES (Local vs Base)", item['base'], item['yours'])
            print_diff("THEIR CHANGES (Upstream vs Base)", item['base'], item['theirs'])
        else:
            print("[Binary file - diff unavailable]")

        print("\nOptions: [t]ake theirs, [k]eep yours, [m]erge")
        while True:
            choice = input("  Select action [t/k/m]: ").strip().lower()
            if choice == 'k':
                print("  -> Keeping local version.")
                break
            elif choice == 't':
                print("  -> Overwriting with upstream.")
                run_cmd(["git", "checkout", branch_name, "--", local_file], cwd=source_dir)
                processed += 1
                break
            elif choice == 'm':
                if item['is_bin']:
                    print("  [!] Cannot auto-merge binary. Choose t or k.")
                    continue
                
                print("  -> Attempting 3-way merge...")
                with tempfile.NamedTemporaryFile(mode='wb', delete=False) as f_base, \
                     tempfile.NamedTemporaryFile(mode='wb', delete=False) as f_theirs:
                    f_base.write(item['base'])
                    f_theirs.write(item['theirs'])
                    f_base_path, f_theirs_path = f_base.name, f_theirs.name

                ret_code = 0
                try:
                    proc = subprocess.run(
                        ["git", "merge-file", "-L", "current", "-L", "base", "-L", "incoming", str(source_dir / local_file), f_base_path, f_theirs_path],
                        cwd=source_dir, stdout=subprocess.DEVNULL
                    )
                    ret_code = proc.returncode
                except:
                    print("  [!] Merge failed.")
                
                os.remove(f_base_path)
                os.remove(f_theirs_path)

                if ret_code == 0:
                    print("  ✅ Auto-merge successful! (No markers needed)")
                else:
                    print("  ⚠️  Conflict markers added. Opening editor...")
                    editor = os.environ.get('EDITOR', 'nano')
                    subprocess.call([editor, str(source_dir / local_file)])
                processed += 1
                break

    print(f"\n✅ Merge Complete. Updated {len(auto_merge_list) + processed} files.")
    print("\n-> Would you like to see the final 'chezmoi diff'? (y/n)")
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
    run_cmd(f"git checkout -", cwd=source_dir)
    
    show_summary(source_dir, args.branch, upstream_changes, inner_path)

    if upstream_changes:
        print(f"\n-> Found {len(upstream_changes)} files changed upstream.")
        print(f"   Would you like to run the Smart Merge wizard? (y/n)")
        if input("   > ").strip().lower() == 'y':
            smart_merge(source_dir, target_repo_path, args.branch, upstream_changes, old_commit, new_commit, inner_path)

if __name__ == "__main__":
    main()