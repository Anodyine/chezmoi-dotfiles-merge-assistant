# merger.py
import os
import sys
import subprocess
import tempfile
import difflib
from pathlib import Path

# Local imports
import utils
import paths

def is_binary(content):
    return b'\0' in content if content else False

def print_diff(label, content_a, content_b):
    print(f"\n--- {label} ---")
    try:
        a_str = content_a.decode('utf-8').splitlines(keepends=True)
        b_str = content_b.decode('utf-8').splitlines(keepends=True)
        diff = difflib.unified_diff(a_str, b_str, fromfile="Base", tofile="New", n=0)
        has_output = False
        for line in diff:
            has_output = True
            if line.startswith('+'): print(f"\033[32m{line.strip()}\033[0m")
            elif line.startswith('-'): print(f"\033[31m{line.strip()}\033[0m")
            elif line.startswith('@'): print(f"\033[36m{line.strip()}\033[0m")
        if not has_output: print("(No text changes detected)")
    except Exception:
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

    changes = utils.run_cmd(f"git diff --name-status HEAD..{branch_name}", cwd=source_dir, capture=True)
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
        clean_upstream = [paths.clean_upstream_path(f, inner_path) for f in upstream_changes]
        for mod_file in modified:
            norm_mod = paths.normalize_chezmoi_path(mod_file)
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
    
    remote_url = utils.get_git_remote_url(source_dir)
    if remote_url:
        print("\n" + "="*60)
        print(f"COMPARE HERE: {remote_url}/compare/{branch_name}?expand=1")
        print("="*60 + "\n")

def smart_merge(source_dir, cache_repo_path, branch_name, upstream_changes, old_commit, new_commit, inner_path):
    if not upstream_changes: return

    auto_merge_list, conflict_list = [], []

    print("-> Analyzing changes...")
    for upstream_file in upstream_changes:
        local_file = paths.find_local_match(source_dir, upstream_file, inner_path)
        if not local_file: continue
        
        full_local_path = source_dir / local_file
        
        # FIX: We now use the full upstream path relative to the cache root
        # instead of trying to split the directory name.
        base_content = utils.get_file_content_at_commit(cache_repo_path, old_commit, upstream_file)
        theirs_content = utils.get_file_content_at_commit(cache_repo_path, new_commit, upstream_file)
        
        try:
            with open(full_local_path, 'rb') as f: yours_content = f.read()
        except: yours_content = None

        if base_content is None or theirs_content is None or yours_content is None:
            # If we can't find the base (likely a brand new file), we treat it as a conflict to be safe
            if base_content is None: base_content = b""
            else: continue

        # Standard normalization for comparison
        is_bin = is_binary(base_content) or is_binary(yours_content) or is_binary(theirs_content)
        
        # Logic for determining auto-merge vs conflict...
        if not is_bin:
            y_s, b_s, t_s = yours_content.strip(), base_content.strip(), theirs_content.strip()
            if y_s == t_s: continue
            elif y_s == b_s: auto_merge_list.append((local_file, upstream_file))
            else:
                conflict_list.append({'local': local_file, 'base': base_content, 'yours': yours_content, 'theirs': theirs_content, 'is_bin': False})
        else:
            if yours_content == theirs_content: continue
            elif yours_content == base_content: auto_merge_list.append((local_file, upstream_file))
            else:
                conflict_list.append({'local': local_file, 'base': base_content, 'yours': yours_content, 'theirs': theirs_content, 'is_bin': True})

    # ACTION: Auto-Updates
    if auto_merge_list:
        print(f"\n-> Automatically updating {len(auto_merge_list)} files from upstream...")
        files_to_checkout = [x[0] for x in auto_merge_list]
        utils.run_cmd(["git", "checkout", branch_name, "--"] + files_to_checkout, cwd=source_dir)
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
                utils.run_cmd(["git", "checkout", branch_name, "--", local_file], cwd=source_dir)
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
                except Exception:
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