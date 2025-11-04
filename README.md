# engine_commit_data

```
# To select which open bench instances to use, the INSTANCES variable in
# the script must be edited
python extract_openbench_html.py
python extract_fishtest_data.py
```

```
# This script extracts the diff and relevant files from the test info
# and the github repos. However only focuses on the search code
# so for a more general use it needs to be adapted. This should
# only be used to give an idea how it can be done
python create_dataset_file.py \
       --remove_comments \
       --input resources/results_fishtest/tests.json \
       --output resources/diff_dataset_fishtest.json \
       --repos_base_dir resources/results_fishtest/git_repos/
```
