# paths.py

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