# stemmero

## Agent skills

### Issue tracker

Specs and tickets live in GitHub Issues for `monstermus/stemmero`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five default triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` and `docs/adr/`. Before exploration, read `docs/agents/domain.md` for consumer rules.

## Windows builds

Before changing packaging or publishing a release, read `README.md` for build commands, versioning and the limits of automated Windows verification. Keep the app and installer version equal. Run `python -m unittest discover -s tests -v` after changes to audio logic or settings.
