# utils.py
import sys
import subprocess
from pathlib import Path

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
    # FIX: If we have a new commit but no old one, treat all files as "changed"
    if not new_commit:
        return []
    
    if not old_commit or old_commit == new_commit:
        # Get list of all files currently in the repo at this path
        cmd = f"git ls-tree -r --name-only {new_commit}"
        output = run_cmd(cmd, cwd=repo_path, capture=True, exit_on_fail=False)
    else:
        # Standard diff between two points
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