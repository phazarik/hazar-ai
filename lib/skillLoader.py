# ----------------------------------------------------------------------------
# Optional skill loader
#
# Reads skills only from ~/.claude/skills/<skill-name>/SKILL.md.
# Installed folders appear in the CLI list and browser selector.
# Local Markdown references can be included from the references folder.
# Inspection shows full text; prompt injection uses a smaller text limit.
# ----------------------------------------------------------------------------

import os
import re
SKILLS_BASE = os.path.expanduser("~/.claude/skills")
SKILL_CHAR_LIMIT = 3000

## Return UTF-8 text, or an empty string if the file cannot be read.
def readFile(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as skillFile: return skillFile.read().strip()
    except (OSError, UnicodeError): return ""

## List installed skill folders; missing folders produce an empty list.
## List only usable folder names with an actual SKILL.md file.
def listSkills() -> list[str]:
    if not os.path.isdir(SKILLS_BASE): return []
    found = []
    for name in os.listdir(SKILLS_BASE):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name): continue
        skillFile = os.path.join(SKILLS_BASE, name, "SKILL.md")
        if os.path.isfile(skillFile): found.append(name)
    return sorted(found)

def loadSkill(name: str, fullText: bool = False) -> str | None:
    # -----------------------------------------------------------------------
    # Read SKILL.md and local Markdown references.
    # Only files within the skill's references directory are included.
    # Inspection returns the complete expanded text. Prompt injection limits
    # the text to 3,000 characters, preferably ending at a line boundary.
    # -----------------------------------------------------------------------
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name): return None
    skillDir = os.path.join(SKILLS_BASE, name)
    skillFile = os.path.join(skillDir, "SKILL.md")
    if not os.path.isfile(skillFile): return None
    content = readFile(skillFile)

    ## References must remain inside the selected skill, even after links are resolved.
    referencesDir = os.path.realpath(os.path.join(skillDir, "references"))
    refPattern = re.compile(r"(?:\./)?references/([A-Za-z0-9_./-]+\.md)")

    ## Process each reference name once so repeated links do not trigger repeated reads.
    for refName in dict.fromkeys(refPattern.findall(content)):
        refPath = os.path.realpath(os.path.join(referencesDir, refName))

        ## Compare full path components; a matching text prefix alone is not enough.
        try: contained = os.path.commonpath([referencesDir, refPath]) == referencesDir
        except ValueError: contained = False
        if contained and os.path.isfile(refPath):
            reference = readFile(refPath)
            content = content.replace(f"references/{refName}",
                                      f"\n--- BEGIN {refName} ---\n{reference}\n--- END {refName} ---\n",)
            
    ## Inspection keeps all text. Only prompt injection gets the character limit.
    if fullText or len(content) <= SKILL_CHAR_LIMIT: return content
    truncated = content[:SKILL_CHAR_LIMIT]
    
    ## Prefer a nearby line break so truncation does not split the last instruction mid-line.
    lastNewline = truncated.rfind("\n")
    if lastNewline > SKILL_CHAR_LIMIT * 0.8: truncated = truncated[:lastNewline]
    return (
        truncated
        + f"\n\n[SKILL TRUNCATED: showing {len(truncated):,} of "
        + f"{len(content):,} chars. Use --skill-inspect {name} for full text.]"
    )

## Build an optional system message without changing the active task.
## Mark the skill as optional and keep the active user task in charge.
def buildSkillMessages(name: str) -> list[dict] | None:
    #text = loadSkill(name)
    text = loadSkill(name, fullText=True) ## -> Change this for putting an upper cap on skill length.
    if text is None: return None
    content = f"[OPTIONAL SKILL: {name}]\n{text}\nFollow the active user task."
    return [{"role": "system", "content": content}]
