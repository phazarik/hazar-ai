#!/usr/bin/env python3
# ------------------------------------------------------------------------------
# This module handles loading and injecting "skills" (custom system prompts)
# into the LLM context. Skills are loaded dynamically from the local directory.
# To prevent huge skills from consuming all available tokens, oversized
# instructions are automatically truncated unless explicitly requested.
# ------------------------------------------------------------------------------

import os, re
BASE_DIR         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_BASE = os.path.expanduser("~/.claude/skills")
SKILL_CHAR_LIMIT = 3000    # ~750 tokens — enough for instructions, not entire reference books
IGNORE_FILES     = {"README.md", "LICENSE", "LICENSE.md", ".gitignore"}

# Safely reads a text file, returning an empty string if it fails or is missing
def readFile(path: str) -> str:
    if not os.path.exists(path): return ""
    with open(path, "r", encoding="utf-8") as f: return f.read().strip()

# Lists all valid skills (folders containing a SKILL.md file)
def listSkills() -> list[str]:
    if not os.path.isdir(SKILLS_BASE): return []
    return [
        folder for folder in os.listdir(SKILLS_BASE)
        if os.path.isdir(os.path.join(SKILLS_BASE, folder))
        and os.path.isfile(os.path.join(SKILLS_BASE, folder, "SKILL.md"))
    ]

# Loads a skill's markdown, inlines any referenced files, and limits the length
def loadSkill(name: str, fullText: bool = False) -> str | None:
    skillDir  = os.path.join(SKILLS_BASE, name)
    skillFile = os.path.join(skillDir, "SKILL.md")
    if not os.path.isfile(skillFile): return None
    content = readFile(skillFile)

    # Automatically find and inline any local markdown files referenced in the skill
    refPattern = re.compile(r"(?:\.\/)?references\/(\S+\.md)")
    for refName in refPattern.findall(content):
        refPath = os.path.join(skillDir, "references", refName)
        if os.path.isfile(refPath):
            refContent = readFile(refPath)
            content = content.replace(
                f"references/{refName}",
                f"\n--- BEGIN {refName} ---\n{refContent}\n--- END {refName} ---\n"
            )

    # If the user just wants to inspect the skill, return it without cutting it
    if fullText: return content

    # Truncate oversized skills to save token space for the actual conversation
    if len(content) > SKILL_CHAR_LIMIT:
        truncated = content[:SKILL_CHAR_LIMIT]

        # Try to cut at the last newline instead of chopping a word in half
        lastNewline = truncated.rfind("\n")
        if lastNewline > SKILL_CHAR_LIMIT * 0.8: truncated = truncated[:lastNewline]

        totalChars = len(content)
        content = (
            truncated
            + f"\n\n[SKILL TRUNCATED: showing {len(truncated):,} of {totalChars:,} chars "
            + f"to save context. Use --skill-inspect {name} to view the full skill.]"
        )
    return content

# Prepares the chat messages required to inject a skill into the LLM context
def buildSkillMessages(name: str) -> list[dict] | None:
    text = loadSkill(name)
    if text is None: return None
    return [
        {
            "role": "user",
            "content": (
                f"[SKILL: {name}]\n"
                f"Apply these instructions to every response in this session.\n\n{text}"
            )
        },
        {
            "role": "assistant",
            "content": f"Understood. Applying {name} skill instructions."
        }
    ]
