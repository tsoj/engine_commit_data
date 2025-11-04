import os
import subprocess
from pathlib import Path
import requests
import tempfile
import time

# TODO add logging

def add_orphaned_commit(clone_dir, repo_url, commit_hash):
    # Extract commit hash from URL
    # commit_hash = commit_url.rstrip('/').split('/')[-1]

    # Setup API URL
    user_and_repo = repo_url.split("github.com/")[1]
    api_url = f"https://api.github.com/repos/{user_and_repo}/commits/{commit_hash}"

    # print("api_url:", api_url)

    # print(f"<{os.environ.get('GITHUB_TOKEN')}>")

    headers = {
        'Authorization': f"token {os.environ.get('GITHUB_TOKEN')}",
        'Accept': 'application/vnd.github.v3+json'
    } if os.environ.get('GITHUB_TOKEN') not in ["", None] else {
        'Accept': 'application/vnd.github.v3+json'
    }
    # Get commit info from GitHub API
    while True:
        response = requests.get(api_url, headers=headers)

        if response.status_code == 401:
            print("Got 401, the used GITHUB_TOKEN is probably out of date.")

        if response.status_code not in [403, 429]:
            break
        print(f"Got {response.status_code}, we're probably out of GitHub API calls. Setting the environment variable GITHUB_TOKEN might improve the situation.")
        print("Waiting for 10 minutes.")
        time.sleep(10.0 * 60.0)
        print("Trying again")
    if response.status_code == 422:
        return commit_hash
    if response.status_code != 200:
        print("api_url:", api_url)
        raise Exception(f"Failed to get commit info: {response.status_code}")

    commit_data = response.json()
    parent_hash = commit_data['parents'][0]['sha']  # Assumes first parent

    # Get the patch
    diff_url = f"https://api.github.com/repos/{user_and_repo}/commits/{commit_hash}"
    # print("patch_url:", diff_url)
    diff_response = requests.get(diff_url, headers=headers)
    if diff_response.status_code != 200:
        print("diff_url:", diff_url)
        raise Exception(f"Failed to get patch: {diff_response.status_code}")

    with tempfile.TemporaryDirectory() as temp_dir:
        # Clone the mirror to create a temporary working tree
        subprocess.run(['git', 'clone', "--quiet", clone_dir, temp_dir], env={"GIT_LFS_SKIP_SMUDGE": "1"}, check=True)

        # Create temporary file for patch
        diff_file = os.path.join(temp_dir, 'commit.diff')
        with open(diff_file, 'w') as f:
            f.write(diff_response.text)

        # Change to temp directory
        original_dir = os.getcwd()
        os.chdir(temp_dir)

        try:
            # Checkout parent commit
            subprocess.run(['git', 'checkout', "--quiet", parent_hash], env={"GIT_LFS_SKIP_SMUDGE": "1"}, check=True)

            # Apply the diff
            subprocess.run(['git', 'apply', "--quiet", diff_file], check=True)

            # Commit the changes
            # First get the commit message from the API data
            original_author = commit_data['commit']['author']
            original_committer = commit_data['commit']['committer']
            commit_msg = commit_data['commit']['message']

            result = subprocess.run(['git', 'diff', '--name-only'],
                                 capture_output=True, text=True, check=True)
            changed_files = result.stdout.splitlines()

            # Add only the changed files
            for file in changed_files:
                subprocess.run(['git', 'add', file], check=True)

            # Create commit with original metadata
            env = os.environ.copy()
            env['GIT_AUTHOR_NAME'] = original_author['name']
            env['GIT_AUTHOR_EMAIL'] = original_author['email']
            env['GIT_AUTHOR_DATE'] = original_author['date']
            env['GIT_COMMITTER_NAME'] = original_committer['name']
            env['GIT_COMMITTER_EMAIL'] = original_committer['email']
            env['GIT_COMMITTER_DATE'] = original_committer['date']

            subprocess.run(['git', 'commit', "--quiet", '-m', commit_msg], env=env, check=True)

            # Get the new commit hash
            result = subprocess.run(['git', 'rev-parse', 'HEAD'],
                                 capture_output=True, text=True, check=True)
            new_commit = result.stdout.strip()

            result = subprocess.run(['git', 'diff', parent_hash],
                                 capture_output=True, text=True, check=True)

            original_diff = diff_response.text.replace("\r", "")
            new_diff = result.stdout.replace("\r", "")

            if original_diff == new_diff:


                # Push the new commit back to the mirror
                branch_name = f"orphaned-{commit_hash[:7]}"
                subprocess.run(['git', 'push', "--quiet", 'origin', f'{new_commit}:refs/heads/{branch_name}'],
                            check=True)

        finally:
            os.chdir(original_dir)

    return new_commit

def commit_exists(clone_dir, commit):
    return subprocess.run(["git", "-C", clone_dir, "cat-file", "-e", commit], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0

def commit_exists_or_find_it(clone_dir, repo_url, commit):
    if commit_exists(clone_dir, commit):
        return commit, True

    try:
        commit = add_orphaned_commit(clone_dir, repo_url, commit)
    except Exception as e:
        print(repo_url, commit)
        print(e)

    return commit, commit_exists(clone_dir, commit)

failed_urls = set()

# Function to mirror repo and check commits
def mirror_and_check_commits(git_repo_dir, repo_url, commit1, commit2):
    assert "https://" in repo_url

    if repo_url in failed_urls:
        return commit1, commit2, False

    user_name, repo_name = repo_url.split('/')[-2:]
    clone_dir = os.path.join(git_repo_dir, user_name, repo_name)

    # Clone (mirror) the repo
    if not Path(clone_dir).exists():
        status = subprocess.run(["git", "clone", "--quiet", "--mirror", repo_url + ".git", clone_dir], env={"GIT_TERMINAL_PROMPT": "0"}).returncode
        if status != 0:
            print(f"Couldn't clone repo {repo_url}, status: {status}")
            failed_urls.add(repo_url)
            return commit1, commit2, False
    else:
        status = subprocess.run(["git", "--git-dir", clone_dir,  "remote", "update"], env={"GIT_TERMINAL_PROMPT": "0"}, stderr=subprocess.DEVNULL).returncode
        if status != 0:
            print(f"WARNING: Couldn't update repo {repo_url}, status: {status}")


    # Check if both commits exist in the mirror

    commit1, commit1_exists = commit_exists_or_find_it(clone_dir, repo_url, commit1)
    commit2, commit2_exists = commit_exists_or_find_it(clone_dir, repo_url, commit2)

    return commit1, commit2, commit1_exists and commit2_exists
