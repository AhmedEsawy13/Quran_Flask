<!-- quranlab-sdk:begin -->
## Quran Lab SDK
This project uses Quran Lab's TajweedFormer SDK. Skill: https://portal.quranlab.ai/skills/quranlab-sdk/SKILL.md, version 2026-11-10.2, installed at .claude/skills/quranlab-sdk/SKILL.md.
Before any change that touches the Quran Lab SDK, fetch https://api.quranlab.ai/v1/sdk/latest and compare the `version` of each platform this project uses (android, apple, web, c) with the version pinned in its build files. If a newer one exists, tell the developer in one line (version, `summary`, `severity`) and offer to upgrade with the skill's "Updating the SDK"; never upgrade without their yes. A `required` severity (security or model compatibility) goes first, stated plainly.
When the developer asks to update the skill, fetch https://portal.quranlab.ai/skills/quranlab-sdk/VERSION; if it differs from the version above, refetch the skill into .claude/skills/quranlab-sdk/SKILL.md and update this block.
<!-- quranlab-sdk:end -->
