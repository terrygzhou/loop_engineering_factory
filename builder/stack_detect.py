"""
Tech stack detector — parse solution.md to extract build-time toolchain.

Authoritative source: human-approved PLAN phase output (solution.md).
If approved architecture has JavaScript → Node.js enters scope.
If Java → JDK + Maven. If Go → Go. Etc.
"""
import re
import subprocess
from typing import Optional


# Mapping: keyword pattern → (apt package, verify command)
STACK_RECIPES: dict[str, tuple[str, str]] = {
    "node": ("nodejs", "node --version"),
    "npm": ("npm", "npm --version"),
    "npx": ("npm", "npx --version"),
    "typescript": ("typescript", "tsc --version"),
    "java": ("openjdk-21-jdk", "java --version"),
    "maven": ("maven", "mvn --version"),
    "gradle": ("gradle", "gradle --version"),
    "go": ("golang-go", "go version"),
    "rust": ("cargo", "cargo --version"),
    "rustup": ("rustc", "rustc --version"),
    "ruby": ("ruby-full", "ruby --version"),
    "bundler": ("bundler", "bundle --version"),
    "elixir": ("elixir", "elixir --version"),
    "mix": ("elixir", "mix --version"),
    "deno": ("deno", "deno --version"),
    "bun": ("bun", "bun --version"),
    "yarn": ("yarn", "yarn --version"),
    "pnpm": ("pnpm", "pnpm --version"),
}


def detect_tech_stack(solution_md: str) -> list[str]:
    """
    Parse solution.md and return list of runtime keywords to install.

    Looks for:
    - **Tech Stack:** line (primary signal)
    - Framework mentions in task descriptions (secondary signal)
    - Command references (npm, cargo, go run, etc.) as tertiary signal

    Returns deduplicated list of keywords like ["nodejs", "npm", "typescript"].
    """
    if not solution_md:
        return []

    stack_line = _extract_tech_stack_line(solution_md)
    keywords = set()

    # Primary: parse **Tech Stack:** line
    if stack_line:
        keywords.update(_parse_stack_line(stack_line))

    # Secondary: scan for framework/tool mentions in task goals
    keywords.update(_scan_frameworks(solution_md))

    # Tertiary: scan for tool commands in verification blocks
    keywords.update(_scan_commands(solution_md))

    # Expand: if "node" is detected, always include npm too
    if "node" in keywords or "nodejs" in keywords:
        keywords.add("npm")
        keywords.add("npx")

    # Resolve to apt-installable package names
    packages = _resolve_to_packages(keywords)

    return sorted(set(packages))


def _extract_tech_stack_line(solution_md: str) -> Optional[str]:
    """Extract the **Tech Stack:** line from solution.md."""
    match = re.search(r'\*\*Tech Stack:\*\*\s*(.+)', solution_md)
    if match:
        return match.group(1).strip()
    return None


def _parse_stack_line(line: str) -> set[str]:
    """Parse a tech stack line into keyword set."""
    keywords = set()
    for pattern in STACK_RECIPES:
        if pattern.lower() in line.lower():
            keywords.add(pattern)
    return keywords


def _scan_frameworks(solution_md: str) -> set[str]:
    """Secondary scan: look for framework/tool mentions in task descriptions."""
    keywords = set()
    # Use regex word boundary matching to avoid false positives
    # (e.g. "gin" != "Gin" framework — "gin" matches "engineering")
    framework_patterns = {
        r'\breact\b': ["node"],
        r'\bvue\b': ["node"],
        r'\bangular\b': ["node"],
        r'\bnext\.js\b': ["node"],
        r'\bsvelte\b': ["node"],
        r'\bnuxt\b': ["node"],
        r'\bremix\b': ["node"],
        r'\bspring boot\b': ["java", "maven"],
        r'\bspring\b': ["java"],
        r'\bgolang\b': ["go"],
        r'\bGin\b': ["go"],            # Gin is case-sensitive in Go ecosystem
        r'\bactix\b': ["rust"],
        r'\brocket\b': ["rust"],
    }
    md_lower = solution_md.lower()
    # For case-sensitive patterns (Gin), check original text too
    for pattern, implied in framework_patterns.items():
        if pattern == r'\bGin\b':
            # Case-sensitive: "Gin" not "gin"
            if re.search(pattern, solution_md):
                keywords.update(implied)
        elif re.search(pattern, md_lower):
            keywords.update(implied)
    return keywords


def _scan_commands(solution_md: str) -> set[str]:
    """Tertiary scan: look for tool command references."""
    keywords = set()
    # Use specific patterns to avoid false positives (e.g. "goal" != "go")
    command_patterns = {
        r'\bnpm\b': "node",
        r'\bnpx\b': "node",
        r'\bcargo\b': "rust",
        r'\bgolang\b': "go",             # explicit golang
        r'\bGo 1\.\d+\b': "go",         # "Go 1.21" version specifier
        r'\bgo run\b': "go",             # "go run main.go"
        r'\bgo build\b': "go",            # "go build ."
        r'\bgo test\b': "go",             # "go test ./..."
        r'\bgo mod\b': "go",              # "go mod init"
        r'\bmvn\b': "maven",
        r'\bgradle\b': "gradle",
        r'\bbun\b': "bun",
        r'\bdeno\b': "deno",
        r'\byarn\b': "node",
        r'\bpnpm\b': "pnpm",
        r'\bbundle\b': "bundler",
        r'\bmix\b': "mix",
    }
    for pattern, keyword in command_patterns.items():
        if re.search(pattern, solution_md):
            keywords.add(keyword)
    return keywords


def _resolve_to_packages(keywords: set[str]) -> list[str]:
    """Map detected keywords to apt package names."""
    packages = []
    for kw in keywords:
        if kw in STACK_RECIPES:
            pkg, _ = STACK_RECIPES[kw]
            packages.append(pkg)
    return packages


def needs_provisioning(solution_md: str) -> bool:
    """Quick check: does this project need any toolchain provisioning?"""
    if not solution_md:
        return False
    # Python-only projects never need provisioning (already in base image)
    # Check if there's a tech stack line mentioning anything beyond Python
    stack_line = _extract_tech_line_or_fallback(solution_md)
    if not stack_line:
        return False
    stack_lower = stack_line.lower()
    # If it's purely Python/FastAPI/SQLAlchemy/Django — no provisioning needed
    python_only = all(
        kw in stack_lower
        for kw in ["python"]
    ) or ("python" in stack_lower and not any(
        kw in stack_lower for kw in ["node", "react", "java", "go", "rust", "ruby", "elixir"]
    ))
    return not python_only


def _extract_tech_line_or_fallback(solution_md: str) -> Optional[str]:
    """Get tech stack line or return None."""
    return _extract_tech_stack_line(solution_md)


def check_existing_tools(packages: list[str]) -> list[str]:
    """
    Check which tools are already installed.
    Returns list of packages that still need installation.
    """
    missing = []
    for pkg in packages:
        if pkg == "nodejs":
            cmd = "node --version"
        elif pkg == "npm":
            cmd = "npm --version"
        elif pkg == "openjdk-21-jdk":
            cmd = "java --version"
        elif pkg == "maven":
            cmd = "mvn --version"
        elif pkg == "golang-go":
            cmd = "go version"
        elif pkg == "cargo" or pkg == "rustc":
            cmd = "cargo --version"
        elif pkg == "rustup":
            cmd = "rustc --version"
        elif pkg == "typescript":
            cmd = "tsc --version"
        elif pkg == "gradle":
            cmd = "gradle --version"
        elif pkg == "ruby-full":
            cmd = "ruby --version"
        elif pkg == "elixir":
            cmd = "elixir --version"
        elif pkg == "deno":
            cmd = "deno --version"
        elif pkg == "bun":
            cmd = "bun --version"
        elif pkg == "yarn":
            cmd = "yarn --version"
        elif pkg == "pnpm":
            cmd = "pnpm --version"
        elif pkg == "bundler":
            cmd = "bundle --version"
        else:
            # Default: try dpkg to check if installed
            result = subprocess.run(
                ["dpkg", "-l", pkg],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                continue
            missing.append(pkg)
            continue

        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True
        )
        if result.returncode != 0:
            missing.append(pkg)

    return missing


def provision_tools(solution_md: str) -> tuple[bool, list[str], str, str]:
    """
    Detect and install missing tools from solution.md.
    Returns (success, packages_installed, stdout, stderr).
    """
    packages = detect_tech_stack(solution_md)
    if not packages:
        return True, [], "No additional tools needed", ""

    missing = check_existing_tools(packages)
    if not missing:
        return True, [], f"All tools already installed: {', '.join(packages)}", ""

    # Install missing tools
    install_cmd = "apt-get update && apt-get install -y " + " ".join(missing)
    print(f"  → [STACK_DETECT] Installing: {', '.join(missing)}")

    result = subprocess.run(
        install_cmd, shell=True, capture_output=True, text=True, timeout=300
    )

    if result.returncode != 0:
        return False, [], f"Failed to install: {result.stderr[:500]}", result.stderr
    else:
        return True, missing, f"Installed: {', '.join(missing)}", result.stderr