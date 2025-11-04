import requests
import json
from pathlib import Path
import shutil
import time
from datetime import datetime
from tqdm import tqdm
from mirror_repos import mirror_and_check_commits
from commit_data import SPRTResults, TestEntry, RunEntryList

RESULT_DIR = "resources/results_fishtest"
GIT_REPO_DIR = RESULT_DIR + "/git_repos"
TEST_JSON_FILE_NAME = RESULT_DIR + "/tests.json"

def main():

    if Path(RESULT_DIR).exists():
        backup_dir = RESULT_DIR + "_backup"
        shutil.copytree(RESULT_DIR, backup_dir)
        Path(TEST_JSON_FILE_NAME).unlink(missing_ok=True)


    run_entries = RunEntryList([])

    num_exists = 0
    page = 1
    while True:
        assert page >= 1
        url = f"https://tests.stockfishchess.org/api/finished_runs?page={page}"  # Provide your HTML file URL here
        # time.sleep(1.0)
        try:
            response = requests.get(url)
        except Exception as e:
            print(e)
            print("Waiting a bit, because we couldn't get this url:", url)
            time.sleep(10.0)
            print("Trying again")
            continue

        content = json.loads(response.content)
        if len(content) == 0:
            break

        for key, entry in tqdm(content.items(), leave=False):
            # print(entry)
            # assert False
            args = entry["args"]
            results = entry["results"]
            if not args["tests_repo"]:
                args["tests_repo"] = "https://github.com/official-stockfish/Stockfish"

            args["resolved_base"], args["resolved_new"], exists = mirror_and_check_commits(GIT_REPO_DIR, args["tests_repo"], args["resolved_base"], args["resolved_new"])
            if exists:
                num_exists += 1

            try:
                date_format = "%Y-%m-%d %H:%M:%S.%f%z"
                date = datetime.strptime(entry["start_time"], date_format)
            except Exception as e:
                print(e)
                print(f"Couldn't get date: {entry}")
                continue

            entry = TestEntry(
                user=args["username"],
                engine="Stockfish",
                testname=args["new_tag"],
                base_hash=args["resolved_base"],
                new_hash=args["resolved_new"],
                exists=exists,
                url=args["tests_repo"],
                time_control=args["tc"],
                statblock="",
                date=date

            )
            if "sprt" in args:
                entry.statblock = str(args["sprt"])
                entry.results = SPRTResults(
                    llr=float(args["sprt"]["llr"]),
                    lower_bound=float(args["sprt"]["lower_bound"]),
                    upper_bound=float(args["sprt"]["upper_bound"]),
                    elo0=float(args["sprt"]["elo0"]),
                    elo1=float(args["sprt"]["elo1"]),
                    pentanomial=list(results.get("pentanomial", [])),
                    wins=int(results["wins"]),
                    losses=int(results["losses"]),
                    draws=int(results["draws"]),
                )

            run_entries.list.append(entry)



        print(f"{num_exists}/{len(run_entries.list)} exist")
        print("Finished page", page)
        page += 1

        with open(TEST_JSON_FILE_NAME, "w") as out_file:
            out_file.write(run_entries.to_json(indent=2))


        # out_file.write(RunEntry.schema().dumps(run_entries, indent=4))

if __name__ == "__main__":
    main()
