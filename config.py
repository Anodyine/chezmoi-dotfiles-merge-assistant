# config.py

DEFAULT_BRANCH = "compare-external"
EXTERNAL_DIR = ".external_sources"
TEMP_TAR = "/tmp/incoming_dots.tar"

CHEZMOI_PREFIXES = (
    "dot_", "private_", "executable_", "exact_", "symlink_", 
    "modify_", "create_", "empty_", "readonly_"
)