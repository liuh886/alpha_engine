# History cleanup gate

Do not start the destructive Git-history rewrite until:

- CN second-round deletions are approved;
- `cn_selected_equities_v3` is merged;
- the selected dataset is exported and checksum-verified;
- a mirror clone and `git bundle --all` backup exist;
- open branches and pull requests depending on old data commits are resolved.
