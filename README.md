Here is a comprehensive `README.md` for the tool. I have structured it to be accessible for beginners while providing the precise commands needed for the advanced workflows we developed.

-----

# Chezmoi Merge Assistant 🤝

**A smarter way to merge upstream dotfile updates.**

If you base your configuration on someone else's dotfiles (e.g., [ML4W](https://github.com/mylinuxforwork/dotfiles), [folke](https://www.google.com/search?q=https://github.com/folke/dotfiles), etc.), staying up to date can be a nightmare. You want their new features and fixes, but you don't want to lose your own customizations.

**Merge Assistant** solves this by automating the heavy lifting. It creates a safe, isolated environment to compare your config against the latest upstream version, detects conflicts, and helps you pick exactly what you want to merge.

## ✨ Features

  * **Safety First:** Runs in a temporary branch. Never touches your `main` branch or your home directory until you say so.
  * **Collision Detection:** Automatically detects files you have modified that the upstream author *also* modified.
  * **News Feed:** Shows you exactly which files were updated upstream since your last pull.
  * **Universal:** Works with any public dotfiles repository (GitHub/GitLab), even if the config is nested in a subfolder.

-----

## 🚀 Installation

This tool is designed to be added as a **submodule** to your existing chezmoi source repository.

1.  Navigate to your chezmoi source directory:

    ```bash
    cd $(chezmoi source-path)
    ```

2.  Add the assistant as a tool (we recommend `tools/merge`):

    ```bash
    git submodule add https://github.com/YOUR_USER/chezmoi-merge-assistant.git tools/merge
    ```

    *(Replace `YOUR_USER` with the actual repo owner).*

3.  Make sure the script is executable:

    ```bash
    chmod +x tools/merge/merge-assistant.py
    ```

4.  **Important:** Add the cache directory to your ignore list. This keeps your repo clean.

    ```bash
    echo ".external_sources/" >> .gitignore
    ```

-----

## 🛠 Usage

To check for updates, run the assistant from your chezmoi source directory.

### Basic Example

If the dotfiles are at the root of the repo (standard structure):

```bash
./tools/merge/merge-assistant.py --repo https://github.com/username/dotfiles.git
```

### Advanced Example (e.g., ML4W)

If the configuration files are inside a subfolder (like `dotfiles/` or `.config/`):

```bash
./tools/merge/merge-assistant.py \
  --repo https://github.com/mylinuxforwork/dotfiles.git \
  --path dotfiles
```

### What happens next?

The tool will:

1.  Download/Update the external repository in a hidden cache.
2.  Create a comparison branch (default: `compare-external`).
3.  **Analyze the changes** and print a summary to your terminal.
4.  Provide a link to a **Pull Request** where you can see the code differences side-by-side.

-----

## 📊 How to Read the Analysis

When the script finishes, it gives you a report like this:

### 1\. Fresh Upstream Updates

> *"These files changed in the external repo since your last pull."*

This is your **News Feed**. It tells you what the author has been working on. If this list is empty, nothing new happened upstream\!

### 2\. Pull Request Preview

> *"Merging the PR will affect these files in your config."*

This lists every file that is different between **You** and **Them**.

  * **[+] NEW FILES:** Features they added that you don't have. (Usually safe to add).
  * **[\*] MODIFIED FILES:** Files where your content differs from theirs.

### 3\. 🚨 ATTENTION REQUIRED (The Danger Zone)

> *"MODIFIED LOCALLY & UPDATED UPSTREAM"*

**Pay attention to this list.**
These are files that **you customized** AND **they updated**.
If you simply overwrite these, you will lose your customizations. If you ignore them, you miss their updates. You must merge these carefully (see workflow below).

-----

## 🛡️ The "Safe Merge" Workflow

Here is the recommended way to process updates without breaking your system.

### Step 1: Run the Assistant

Run the command (see Usage above). **Do not merge the Pull Request on GitHub.** Use the PR only as a visual guide to see what changed.

### Step 2: Shopping Mode (Take what you want)

Go back to your terminal (you are on your `main` branch).

**For New Files (Safe to Add):**
If you see new features in the analysis that you want, grab them:

```bash
git checkout compare-external -- dot_config/waybar/scripts/new-script.sh
```

**For Modified Files (Safe to Update):**
If a file is listed as "Modified" but **NOT** in the "Attention Required" list, it means you probably haven't touched it, so it's safe to update:

```bash
git checkout compare-external -- dot_config/some-app/config
```

### Step 3: Handling Collisions (The "Source of Truth" Method)

For files in the **Attention Required** list (e.g., `dot_config/hypr/hyprland.conf`), follow this process to keep your tweaks:

1.  **Overwrite the file** with the upstream version:

    ```bash
    git checkout compare-external -- dot_config/hypr/hyprland.conf
    ```

    *At this moment, you have lost your customization in the file.*

2.  **Ask Chezmoi what you lost:**
    Run `diff` against your actual home directory (your "Source of Truth").

    ```bash
    chezmoi diff
    ```

      * **Red Lines (-):** These are your custom settings that are currently active on your computer but missing from the file.
      * **Green Lines (+):** These are the new features the author added.

3.  **Re-Apply Your Tweaks:**
    Open the file in your editor and re-add the missing logic (the red lines) manually. This ensures your tweaks are placed correctly within the author's new structure.

4.  **Verify:**
    Run `chezmoi diff` again. If you only see Green lines (new features) or no output, you are done\!

### Step 4: Apply & Cleanup

Once you have pulled in everything you want:

1.  **Apply to your system:**
    ```bash
    chezmoi apply
    ```
2.  **Delete the temporary branch:**
    ```bash
    git branch -D compare-external
    ```

-----

## ❓ FAQ

**Does this run `chezmoi apply` automatically?**
**No.** It operates entirely inside your local git repository. Your actual configuration files in `~/.config` are never touched until you manually run `chezmoi apply` yourself.

**Can I run this multiple times?**
**Yes.** The tool is idempotent. You can run it daily to check for updates. It will automatically update the `compare-external` branch with the latest state.

**Why does it show "Deleted Files"?**
The tool assumes the upstream repo is the "target state." If you have a custom script that the upstream repo *doesn't* have, it shows as "Deleted" in the comparison. You can simply ignore these; you obviously want to keep your own files\!
