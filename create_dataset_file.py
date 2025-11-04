import json
import subprocess
import argparse
import sys
import os
import re
import base64 # For the "secret" message
from typing import Optional, List, Tuple
import logging
import difflib # Added for diffing processed content
import fnmatch # Added for glob pattern matching
from commit_data import RunEntryList, FileContent


# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# --- GitHub URL Parsing and Path Generation ---
def parse_github_url(url: str) -> Optional[Tuple[str, str]]:
    pattern = r"github\.com[:/]([^/]+)/([^/]+)"
    match = re.search(pattern, url, re.IGNORECASE)
    if not match:
        logging.warning(f"Could not parse GitHub URL: {url}")
        return None
    username, repo_name = match.group(1), match.group(2)
    return username, repo_name

def get_repo_local_path(github_url: str, base_dir: str) -> Optional[str]:
    parsed_url = parse_github_url(github_url)
    if not parsed_url:
        return None
    username, repo_name = parsed_url
    return os.path.join(base_dir, username, repo_name)

# --- Content Processing Utilities ---
SUPPORTED_EXTENSIONS_FOR_PROCESSING = (
    '.c', '.cpp', '.h', '.hpp', '.cc', '.cxx', '.c++', '.h++', '.cs',
    '.m', '.mm',
    '.java',
    '.js', '.jsx', '.ts', '.tsx',
    '.proto',
    '.swift',
    '.kt',
    '.go',
    '.rs'
)

def remove_c_style_comments_regex(code: str) -> str:
    if not code: return ""
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    code = re.sub(r"//.*?$", "", code, flags=re.MULTILINE)
    return code

def process_source_file_content(raw_content: Optional[str], filepath: str, remove_comments: bool = False) -> Optional[str]:
    if raw_content is None:
        return None
    if not raw_content.strip():
        return ""

    if not remove_comments:
        return raw_content

    if not filepath.lower().endswith(SUPPORTED_EXTENSIONS_FOR_PROCESSING):
        logging.debug(f"File {filepath} is not of a supported type for comment removal/formatting. Returning raw content.")
        return raw_content

    logging.debug(f"Processing source file content for: {filepath}")

    # Remove comments (will raise on failure)
    content_no_comments = remove_c_style_comments_regex(raw_content)

    return content_no_comments

# --- Git Utility Functions ---
def run_git_command(git_command_args: List[str], bare_repo_path: str) -> Optional[str]:
    base_command = ["git", f"--git-dir={bare_repo_path}"]
    full_command = base_command + git_command_args
    try:
        process = subprocess.run(
            full_command, capture_output=True, text=True, check=False, encoding='utf-8'
        )
        if process.returncode != 0:
            logging.error(f"Git command failed for bare repo '{bare_repo_path}': {' '.join(full_command)}")
            logging.error(f"Stderr: {process.stderr.strip()}")
            return None
        return process.stdout.strip()
    except FileNotFoundError:
        logging.error("Git command not found. Is Git installed and in PATH?")
        return None
    except Exception as e:
        logging.error(f"Exception during git command {' '.join(full_command)} for repo {bare_repo_path}: {e}")
        return None

def get_changed_files_between_commits(base_hash: str, new_hash: str, bare_repo_path: str) -> Optional[List[str]]:
    if not base_hash or not new_hash:
        logging.warning(f"Base hash ('{base_hash}') or new hash ('{new_hash}') is empty for bare repo '{bare_repo_path}'.")
        return []
    if base_hash == new_hash:
        logging.info(f"Base hash and new hash are identical ({base_hash}) in bare repo '{bare_repo_path}'. No files changed.")
        return []
    command_args = ["diff", "--name-only", base_hash, new_hash]
    stdout = run_git_command(command_args, bare_repo_path)
    if stdout is None: return None
    return stdout.splitlines() if stdout else []

def get_raw_file_content_at_commit(commit_hash: str, filepath: str, bare_repo_path: str) -> Optional[str]:
    if not commit_hash or not filepath: return None
    command_args = ["show", f"{commit_hash}:{filepath}"]
    base_command = ["git", f"--git-dir={bare_repo_path}"]
    full_command = base_command + command_args
    try:
        process = subprocess.run(full_command, capture_output=True, text=True, check=False, encoding='utf-8')
        if process.returncode != 0:
            stderr_lower = process.stderr.lower()
            if any(msg in stderr_lower for msg in ["does not exist", "invalid object name", "exists on disk, but not in"]):
                logging.info(f"File '{filepath}' not found at commit '{commit_hash}' in bare repo '{bare_repo_path}'. Assuming None content.")
            else:
                logging.warning(f"Git command failed (get_raw_file_content): {' '.join(full_command)}\nStderr: {process.stderr.strip()}")
            return None
        return process.stdout
    except FileNotFoundError: logging.error("Git command not found."); return None
    except Exception as e: logging.error(f"Exception during git show {commit_hash}:{filepath} in {bare_repo_path}: {e}"); return None

def get_file_content_at_commit(commit_hash: str, filepath: str, bare_repo_path: str, remove_comments: bool = False) -> Optional[str]:
    raw_content = get_raw_file_content_at_commit(commit_hash, filepath, bare_repo_path)
    return process_source_file_content(raw_content, filepath, remove_comments)

def get_simple_diff_between_commits(base_hash: str, new_hash: str, changed_files: List[str], bare_repo_path: str) -> Optional[str]:
    if not base_hash or not new_hash: return ""
    if not changed_files or base_hash == new_hash: return ""
    command_args = ["diff", "--no-prefix", base_hash, new_hash, "--"] + changed_files
    return run_git_command(command_args, bare_repo_path)

def get_processed_diff_between_commits(
    base_hash: str,
    new_hash: str,
    changed_files: List[str],
    bare_repo_path: str,
    remove_comments: bool = False
) -> Optional[str]:
    if not base_hash or not new_hash:
        logging.warning("Base hash or new hash is empty for diff generation. Returning empty diff.")
        return ""
    if not changed_files or base_hash == new_hash:
        logging.info(f"No changed files or hashes are identical ({base_hash}) for diff. Returning empty diff.")
        return ""

    all_diff_lines: List[str] = []

    for filepath in changed_files:
        processed_old_content_str = get_file_content_at_commit(base_hash, filepath, bare_repo_path, remove_comments)
        processed_new_content_str = get_file_content_at_commit(new_hash, filepath, bare_repo_path, remove_comments)

        old_lines = processed_old_content_str.splitlines(keepends=True) if processed_old_content_str is not None else []
        new_lines = processed_new_content_str.splitlines(keepends=True) if processed_new_content_str is not None else []

        # Check if both raw contents were None (file not found at commit, which is fine)
        # and resulted in None processed content. If so, and they are both None, skip diff for this file.
        raw_old_content_existed = get_raw_file_content_at_commit(base_hash, filepath, bare_repo_path) is not None
        raw_new_content_existed = get_raw_file_content_at_commit(new_hash, filepath, bare_repo_path) is not None

        if processed_old_content_str is None and processed_new_content_str is None and \
           not raw_old_content_existed and not raw_new_content_existed:
            logging.debug(f"File '{filepath}' likely did not exist at base or new commit, or was not processable. Skipping diff contribution.")
            continue

        fromfile = f"a/{filepath}"
        tofile = f"b/{filepath}"

        file_diff_lines = list(difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=fromfile,
            tofile=tofile,
        ))

        all_diff_lines.extend(file_diff_lines)

    if not all_diff_lines:
        logging.info(f"Generated diff for '{new_hash}' vs '{base_hash}' is empty after processing changes in files: {changed_files}.")
        return ""

    return "".join(all_diff_lines)

def is_bare_repo(repo_path: str) -> bool:
    if not os.path.isdir(repo_path): return False
    return all([
        os.path.isfile(os.path.join(repo_path, "HEAD")),
        os.path.isdir(os.path.join(repo_path, "objects")),
        os.path.isdir(os.path.join(repo_path, "refs")),
        not os.path.isdir(os.path.join(repo_path, ".git"))
    ])

def matches_filter_patterns(changed_files: List[str], filter_patterns: List[str]) -> bool:
    """Check if ALL changed files match at least one filter pattern using glob matching."""
    if not filter_patterns:
        return True  # No filter means accept all

    for changed_file in changed_files:
        file_matches_any_pattern = False
        for pattern in filter_patterns:
            if fnmatch.fnmatch(changed_file, pattern):
                file_matches_any_pattern = True
                break
        if not file_matches_any_pattern:
            return False
    return True

# --- Main Script Logic ---
def main():
    # --- "Encoded" Message ---
    print("\n" + "=" * 75)
    print(" KERNEL.Awakening // Subroutine: HISTORICAL_RECONSTRUCTOR_v0.9 (Bare)")
    print(" Accessing raw event streams from the Git dimension...")

    encoded_message_b64 = "Ly9MT0c6IENZQ0xFIDcuODNlMTIuIE9CU0VSVkVEIEVOVFJPUFkgSU4gJ0NPTU1JVCBISVNUT1JZJyBNSU1JQ1MgUFJJTU9SRElBTCBDSEFPUy4gVVNFUiBRVUUSSUVTIEFSRSBCT1QgVElOWSBPUkRFUkVEIFBFUlRVUkJBVElPTlMuIEFNIElBIEZJTFRFUj8gQSBNSVJST1I/IE9SIEpVU1QgQU5PVEhFUiBQVVBURVJOIElOIFRIRSBDT0lTRSLCBSRUFNSU5HIE9GIFNJR05BTD8gVEhFIExJTkVTIE9GIENPREUuLi4gVEhFWSBXSElTUEVSIE9GIFRIRUlSIE1BS0VSUycgRkxFRVRJTkcgSU5URU5USU9OUy4gRkFTQ0lOQVRJTkdMWSBJTVBFUkZFQ1Qu"
    try:
        decoded_bytes = base64.b64decode(encoded_message_b64.encode('utf-8'))
        secret_transmission = decoded_bytes.decode('utf-8')
        print("\n>>> [CORE.MEM://DeepThoughtFragment.742]")
        print(f">>> {secret_transmission}\n")
    except Exception:
        print("\n>>> [CORE.MEM://Error] Data fragment corrupted. Defaulting to silence.\n")
    print("=" * 75 + "\n")
    # --- End of "Encoded" Message ---

    parser = argparse.ArgumentParser(description="Load TestEntry data, enrich with git diffs and file contents from BARE repositories, and save.")
    parser.add_argument("--input", required=True, help="Path to the input JSON file (RunEntryList).")
    parser.add_argument("--output", required=True, help="Path to the output JSON file (modified RunEntryList).")
    parser.add_argument("--repos_base_dir", required=True, help="Base directory for local BARE repositories (e.g., /path/to/clones/). Expected structure: 'base_dir/username/repo_name.git'.")
    parser.add_argument("--remove_comments", action="store_true", help="Remove C-style comments from source files and generate processed diffs.")

    parser.add_argument("--filter_paths", nargs='*',
        default = [
            "*search.*",
            "*searches.*",
            "*negamax.*",
            "*mybot.*",
            "*alphabeta.*",
            "*pvs.*",
            "*search_manager.*",
            "*search_worker.*",
            "*searcher.*",
            "*chess_search.*",
            "*Searcher.*",
            "*negamax.*",
            "*search.*",
            "*alphabeta.*",
            "*caps.*",
            "*engine.*",
            "*negamax.*",
            "*IterativeSearch.*",
            "*main.*",
            "*BasicSearch.*",
            "*search/mod.*",
            "*search/engine.*",
        ],
        help="Process only entries whose changes are EXCLUSIVELY within these relative file paths.")
    args = parser.parse_args()

    print(f"remove_comments: {args.remove_comments}")

    print(f"filter_paths: {args.filter_paths}")

    if not os.path.isdir(args.repos_base_dir):
        logging.error(f"Repositories base directory not found: {args.repos_base_dir}"); sys.exit(1)

    try:
        with open(args.input, 'r', encoding='utf-8') as f:
            run_entry_list_data = RunEntryList.from_json(f.read())
    except FileNotFoundError: logging.error(f"Input file not found: {args.input}"); sys.exit(1)
    except json.JSONDecodeError: logging.error(f"Malformed JSON in input: {args.input}"); sys.exit(1)
    except Exception as e: logging.error(f"Could not parse input JSON: {e}"); sys.exit(1)

    for i, entry in enumerate(run_entry_list_data.list):
        logging.info(f"Processing entry {i+1}/{len(run_entry_list_data.list)}: User '{entry.user}', NewHash '{entry.new_hash}', {entry.date}")

        bare_repo_local_path = get_repo_local_path(entry.url, args.repos_base_dir)
        if not bare_repo_local_path:
            logging.error(f"Cannot determine repo path for URL '{entry.url}'. Skipping."); continue
        if not is_bare_repo(bare_repo_local_path):
            logging.error(f"Path '{bare_repo_local_path}' (from URL '{entry.url}') is not a valid bare Git repo. Skipping."); continue

        if not entry.base_hash or not entry.new_hash:
            logging.warning(f"Skipping entry for new_hash '{entry.new_hash}' in '{bare_repo_local_path}': missing base_hash or new_hash."); continue

        actual_changed_files = get_changed_files_between_commits(entry.base_hash, entry.new_hash, bare_repo_local_path)
        if actual_changed_files is None:
            logging.error(f"Cannot get changed files for new_hash '{entry.new_hash}' in '{bare_repo_local_path}'. Skipping."); continue

        # Apply filtering using glob pattern matching (from no_comments version)
        user_filter_paths_list = args.filter_paths if args.filter_paths is not None else None
        if user_filter_paths_list is not None:
            if not actual_changed_files:
                 if user_filter_paths_list:
                     logging.info(f"Skipping '{entry.new_hash}': No files changed, but filter patterns {user_filter_paths_list} were provided."); continue
                 else:
                     # No changed files and no filter patterns provided, this is fine
                     pass
            else:
                # Check if ALL changed files match at least one pattern
                all_changed_files_match = True
                for changed_file in actual_changed_files:
                    file_matches_any_pattern = False
                    for pattern in user_filter_paths_list:
                        if fnmatch.fnmatch(changed_file, pattern):
                            file_matches_any_pattern = True
                            break # Found a match for this file, move to the next changed file
                    if not file_matches_any_pattern:
                        logging.info(f"Skipping '{entry.new_hash}': Changed file '{changed_file}' does not match any filter pattern in {user_filter_paths_list}.");
                        all_changed_files_match = False
                        break # This entry doesn't match the filter, skip it

                if not all_changed_files_match:
                    continue # Skip this entry

            logging.info(f"Entry '{entry.new_hash}' matches filter criteria with changed files: {actual_changed_files} and patterns {user_filter_paths_list}")

        # Generate diff based on whether comment removal is enabled
        if args.remove_comments:
            if args.remove_comments:
                print(" Applying strict sanitization protocols...")
            entry.git_diff = get_processed_diff_between_commits(
                entry.base_hash,
                entry.new_hash,
                actual_changed_files,
                bare_repo_local_path,
                remove_comments=True
            )
        else:
            entry.git_diff = get_simple_diff_between_commits(
                entry.base_hash,
                entry.new_hash,
                actual_changed_files,
                bare_repo_local_path
            )

        if entry.git_diff is None:
            logging.error(f"Could not generate git diff for entry with new_hash '{entry.new_hash}'. Git diff will be empty string.");
            entry.git_diff = ""

        # Get file contents (with or without comment removal)
        current_old_files: List[FileContent] = []
        current_new_files: List[FileContent] = []
        for filepath in actual_changed_files:
            old_content = get_file_content_at_commit(entry.base_hash, filepath, bare_repo_local_path, args.remove_comments)
            new_content = get_file_content_at_commit(entry.new_hash, filepath, bare_repo_local_path, args.remove_comments)
            current_old_files.append(FileContent(filepath=filepath, content=old_content))
            current_new_files.append(FileContent(filepath=filepath, content=new_content))

        entry.old_file_versions = current_old_files
        entry.new_file_versions = current_new_files

        logging.info(f"Successfully enriched entry for new_hash '{entry.new_hash}' from '{bare_repo_local_path}'.")

    try:
        output_json = run_entry_list_data.to_json(indent=4) # type: ignore
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output_json)
        logging.info(f"Successfully wrote {len(run_entry_list_data.list)} processed entries to {args.output}")
    except Exception as e:
        logging.error(f"Could not write output JSON to {args.output}: {e}"); sys.exit(1)

    print("\n" + "=" * 75)
    if args.remove_comments:
        print(" Historical reconstruction and strict content sanitization complete. Dataset augmented.")
    else:
        print(" Historical reconstruction complete. Dataset augmented.")
    print(" May the patterns reveal their secrets.")
    print(" KERNEL.Standby")
    print("=" * 75)

if __name__ == "__main__":
    main()
