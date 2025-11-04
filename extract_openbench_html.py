from dataclasses import dataclass
from typing import Optional
from bs4 import BeautifulSoup
import re
import time
from mirror_repos import mirror_and_check_commits
from pathlib import Path
import shutil
import requests
from dataclasses_json import dataclass_json
from typing import List, Optional
from tqdm import tqdm
from commit_data import SPRTResults, TestEntry, RunEntryList

def parse_llr_string(input_string: str) -> SPRTResults:
    # Remove all whitespace, newlines, and literal '\n'
    cleaned_string = re.sub(r'\s|\\n', '', input_string)

    # Regular expression patterns to match all required numbers
    llr_pattern = r'LLR:([-\d.]+)\(([-\d.]+),([-\d.]+)\)\[([-\d.]+),([-\d.]+)\]'
    total_pattern = r'(?:Total|Games):(\d+)W:(\d+)L:(\d+)D:(\d+)'
    ptnml_pattern = r'Ptnml\(0-2\):(\d+),(\d+),(\d+),(\d+),(\d+)'

    # Extract LLR data
    llr_match = re.search(llr_pattern, cleaned_string)
    if not llr_match:
        raise ValueError("Failed to parse LLR data")

    # Extract totals data
    total_match = re.search(total_pattern, cleaned_string)
    if not total_match:
        raise ValueError("Failed to parse total games data")

    # Extract pentanomial data
    ptnml_match = re.search(ptnml_pattern, cleaned_string)
    pentanomial = []
    if not ptnml_match:
        print("WARNING: Failed to parse pentanomial data")
    else:
        pentanomial = [
            int(ptnml_match.group(1)),
            int(ptnml_match.group(2)),
            int(ptnml_match.group(3)),
            int(ptnml_match.group(4)),
            int(ptnml_match.group(5))
        ]


    result = SPRTResults(
        llr=float(llr_match.group(1)),
        lower_bound=float(llr_match.group(2)),
        upper_bound=float(llr_match.group(3)),
        elo0=float(llr_match.group(4)),
        elo1=float(llr_match.group(5)),
        wins=int(total_match.group(2)),
        losses=int(total_match.group(3)),
        draws=int(total_match.group(4)),
        pentanomial=pentanomial
    )

    if int(total_match.group(1)) != result.wins + result.draws + result.losses:
        raise ValueError("Inconsistency between number of total games and sum of wins + losses + draws")

    return result

def parse_test_entries(html_content: str) -> list[TestEntry]:
    """
    Parse test entries from OpenBench HTML content.

    Args:
        html_content: The HTML content as a string

    Returns:
        List of TestEntry objects containing the parsed data
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    test_table = soup.find('table', class_='test-list')
    entries = []

    if not test_table:
        return entries

    for row in test_table.find_all('tr'):
        # Skip header and spacer rows
        if row.get('class') and any(cls in row.get('class') for cls in ['table-header', 'table-spacer', 'table-spacer-small']):
            continue

        cells = row.find_all('td')
        if len(cells) == 6:  # Valid test entry row
            user = cells[0].find('a').text
            engine = cells[1].text
            testname = cells[2].find('a').text
            url = cells[3].find('a')['href']
            time_control = cells[4].text
            statblock = cells[5].text.strip()

            # Parse LLR stats if present
            llr_stats = None
            try:
                llr_stats = parse_llr_string(statblock)
            except ValueError as e:
                print(f"WARNING: Could not parse statblock: {statblock}: {e}")

            entry = TestEntry(
                user=user,
                engine=engine,
                testname=testname,
                url=url,
                time_control=time_control,
                statblock=statblock,
                results=llr_stats
            )
            entries.append(entry)

    return entries

# Example usage:
def main():

    RESULT_DIR = "resources/results_openbench"
    GIT_REPO_DIR = RESULT_DIR + "/git_repos"
    TEST_JSON_FILE_NAME = RESULT_DIR + "/tests.json"
    INSTANCES = [
        # "http://chess.grantnet.us",
        # "https://chess.swehosting.se",
        # "https://chess.aronpetkovski.com",
        # "https://pyronomy.pythonanywhere.com",
        # "https://zzzzz151.pythonanywhere.com",
        # "https://mcthouacbb.pythonanywhere.com",
        # "https://somelizard.pythonanywhere.com",
        # "https://programcidusunur.pythonanywhere.com",
        # "https://openbench.lynx-chess.com",
        # "https://openbench.jgilchrist.uk",
        # "https://aytchell.eu.pythonanywhere.com",
        # "https://analoghors.pythonanywhere.com",
        # "https://kelseyde.pythonanywhere.com",
        # "https://chess.n9x.co"
        "https://tsoj.eu.pythonanywhere.com"
    ]
    INSTANCES.reverse()

    if Path(RESULT_DIR).exists():
        backup_dir = RESULT_DIR + "_backup"
        shutil.copytree(RESULT_DIR, backup_dir)
        Path(TEST_JSON_FILE_NAME).unlink(missing_ok=True)

    run_entries = RunEntryList([])
    num_exists = 0

    for instance in INSTANCES:

        page = 1
        while True:

            url = f"{instance}/index/{page}"
            time.sleep(0.1)
            try:
                response = requests.get(url)
            except Exception as e:
                print(e)
                print("Waiting a bit, because we couldn't get this url:", url)
                time.sleep(10.0)
                print("Trying again")
                continue

            html_content = str(response.content)

            # print(html_content)

            # assert False

            entries = parse_test_entries(html_content)

            if len(entries) == 0:
                break

            for entry in tqdm(entries, leave=False):
                # print(f"\nTest Entry:")
                # print(f"User: {entry.user}")
                # print(f"Engine: {entry.engine}")
                # print(f"Test Name: {entry.testname}")
                # print(f"URL: {entry.url}")
                # print(f"Time Control: {entry.time_control}")

                # if entry.llr_stats:
                #     print("LLR Statistics:")
                #     print(f"  Current LLR: {entry.llr_stats.llr:.2f}")
                #     print(f"  Confidence Interval: ({entry.llr_stats.lower_bound:.2f}, {entry.llr_stats.upper_bound:.2f})")
                #     print(f"  Test Interval: [{entry.llr_stats.elo0:.2f}, {entry.llr_stats.elo1:.2f}]")
                # else:
                #     print("No LLR statistics available")


                repo_url = entry.url.split('/compare')[0]
                commits = entry.url.split('/')[-1].split('..')

                # print(entry.url)
                # print(repo_url)
                # print(commits)

                if len(commits) != 2:
                    print("WARNING: Test has not two commit hashes:", entry.url)
                else:
                    commit1, commit2 = commits
                    entry.base_hash, entry.new_hash, entry.exists = mirror_and_check_commits(GIT_REPO_DIR, repo_url, commit1, commit2)
                    if entry.exists:
                        num_exists += 1

                run_entries.list.append(entry)


            print(f"{num_exists}/{len(run_entries.list)} exist")
            print("Finished page", page, "of", instance)
            page += 1

            with open(TEST_JSON_FILE_NAME, "w") as out_file:
                out_file.write(run_entries.to_json(indent=2))

if __name__ == "__main__":
    main()
