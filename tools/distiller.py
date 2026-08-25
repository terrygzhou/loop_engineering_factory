"""
Skill instruction extractor — distills SKILL.md to concise LLM prompts.

Strips templates, examples, and boilerplate. Keeps Purpose + Process only.
Enforces max_chars per skill for fast LLM context windows.
"""
import re
from pathlib import Path


def distill_skill(skill_content: str, max_chars: int = 2000) -> str:
    """
    Distill a SKILL.md file to essential instructions for the LLM.
    Returns a truncated string capped at max_chars.
    """
    if skill_content.startswith('---'):
        parts = skill_content.split('---', 2)
        body = parts[2] if len(parts) >= 3 else skill_content
    else:
        body = skill_content

    lines = []

    # Extract purpose/description section
    for heading in ['purpose', 'overview', 'when to use', 'what it does', 'description']:
        match = re.search(
            rf'##\s+(?:{heading})\s*\n(.*?)(?=\n## )',
            body, re.DOTALL | re.IGNORECASE
        )
        if match:
            lines.append(match.group(1).strip())
            break

    # Extract process/workflow/steps section
    for heading in ['process', 'steps', 'standard workflow', 'how to', 'instructions',
                     'workflow', 'guide', 'outline', 'what to do']:
        match = re.search(
            rf'##\s+(?:{heading})\s*\n(.*?)(?=\n## )',
            body, re.DOTALL | re.IGNORECASE
        )
        if match:
            text = re.sub(r'\n{3,}', '\n\n', match.group(1))
            lines.append(text.strip())
            break

    if lines:
        distilled = '\n\n'.join(lines)
    else:
        # Fallback: first 2000 chars of body
        distilled = body[:max_chars]

    # Enforce max_chars
    if len(distilled) > max_chars:
        truncated = distilled[:max_chars]
        # Try to break at paragraph boundary
        last_para = truncated.rfind('\n\n')
        if last_para > max_chars * 0.5:
            truncated = distilled[:last_para]
        distilled = truncated.rstrip() + '\n... (truncated)'

    return distilled


def distill_all_skills(skills_dir: str = './skills') -> dict:
    """Distill all skills in a directory."""
    result: dict = {}
    skills_path = Path(skills_dir)
    if not skills_path.exists():
        return result

    for skill_dir in sorted(skills_path.iterdir()):
        if skill_dir.is_dir():
            skill_md = skill_dir / 'SKILL.md'
            if skill_md.exists():
                content = skill_md.read_text()
                result[skill_dir.name] = distill_skill(content)

    return result


if __name__ == '__main__':
    skills = distill_all_skills('./skills')
    for name, distilled in sorted(skills.items(), key=lambda x: len(x[1]), reverse=True):
        print(f"{name:40s} {len(distilled):5d} chars")
    total = sum(len(v) for v in skills.values())
    print(f"\nTotal: {total:,} chars ({len(skills)} skills)")