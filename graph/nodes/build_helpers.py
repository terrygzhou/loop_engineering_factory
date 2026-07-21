"""
BUILD subgraph helpers — shared utilities for all sub-nodes.
Refactored from build.py, seed_data.py, verify.py.
"""
import os
import re
import subprocess
import yaml
from pathlib import Path
from typing import Optional


def parse_llm_output(text: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]], dict]:
    """Parse LLM output for file content and shell commands."""
    files, commands = [], []
    total_code_blocks = len(re.findall(r'```', text)) // 2

    # Structured FILE blocks
    for m in re.finditer(
        r'===\s*FILE:\s*(.+?)\s*===\s*\n\s*```(\w+)?\s*\n(.*?)```',
        text, re.DOTALL,
    ):
        path, code = m.group(1).strip(), m.group(3).rstrip()
        if code and path:
            files.append((path, code))

    # Structured COMMAND blocks
    for m in re.finditer(
        r'===\s*COMMAND:\s*(.+?)\s*===\s*\n\s*```(\w+)?\s*\n(.*?)```',
        text, re.DOTALL,
    ):
        desc, cmd = m.group(1).strip(), m.group(3).strip()
        if cmd:
            commands.append((desc, cmd))

    # Bare code blocks
    bare_blocks = 0
    for m in re.finditer(r'```(\w+)?\s*\n(.*?)```', text, re.DOTALL):
        lang, code = (m.group(1) or '').strip().lower(), m.group(2).rstrip()
        if m.start() in [fm.start() for fm in re.finditer(r'===\s*(?:FILE|COMMAND):', text)]:
            continue
        bare_blocks += 1
        if lang in ('bash', 'shell'):
            commands.append(('auto-detected', code))
        elif lang in ('python', 'html', 'jinja', 'javascript', 'css', 'sql', 'yaml', 'json', 'dockerfile'):
            first_line = code.split('\n')[0].strip()
            if first_line.startswith('#') and 'path:' in first_line.lower():
                inferred = first_line.split('path:')[1].strip()
                if '/' in inferred or '.' in inferred:
                    files.append((inferred, code))
                    continue

    return files, commands, {
        "markers_found": len(files) + len(commands),
        "bare_blocks": bare_blocks,
        "total_code_blocks": total_code_blocks,
    }


def write_files_to_project(files: list[tuple[str, str]], project_path: str) -> list[str]:
    """Write parsed files to disk. Safety: reject paths escaping project."""
    written = []
    proj = os.path.realpath(project_path)
    for path, content in files:
        target = os.path.realpath(os.path.join(project_path, path))
        if not target.startswith(proj + os.sep) and target != proj:
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'w') as f:
            f.write(content)
        written.append(path)
    return written


def run_command(cmd: str, timeout: int = 180, workdir: Optional[str] = None) -> tuple[int, str, str]:
    """Run a shell command. Returns (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=workdir,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, '', f'Command timed out after {timeout}s: {cmd}'
    except Exception as e:
        return -1, '', f'Execution error: {e}'


def find_docker_project(project_path: str) -> str:
    """Find directory containing docker-compose.yml."""
    from config.loader import config as _cfg
    output_subdir = _cfg.paths.output_subdir
    for candidate in [project_path, os.path.join(project_path, output_subdir)]:
        for pattern in ['docker-compose.yml', 'docker-compose.yaml', 'compose.yml', 'compose.yaml']:
            if os.path.exists(os.path.join(candidate, pattern)):
                return candidate
    return project_path


def resolve_app_service(docker_proj: str) -> str:
    """Discover the app/primary service name from the project's docker-compose file.

    Looks for the service that has `build: .` or `build:` (i.e. the service built
    from the project source).  Falls back to common names: ``app``, ``api``, ``web``.
    """
    for pattern in ['docker-compose.yml', 'docker-compose.yaml', 'compose.yml', 'compose.yaml']:
        compose_path = os.path.join(docker_proj, pattern)
        if os.path.exists(compose_path):
            try:
                with open(compose_path) as f:
                    dc = yaml.safe_load(f) or {}
                services = dc.get('services', {})
                # Priority 1: service with build: . or build: ./
                for svc_name, svc_conf in services.items():
                    if isinstance(svc_conf, dict):
                        build_val = svc_conf.get('build', '')
                        if build_val in ('.', './', '', None) or (isinstance(build_val, str) and build_val.startswith('.')):
                            return svc_name
                # Priority 2: service with a 'ports' mapping that includes common app ports
                for svc_name, svc_conf in services.items():
                    if isinstance(svc_conf, dict) and svc_conf.get('ports'):
                        return svc_name
                # Priority 3: first non-db/non-infra service
                skip = {'db', 'database', 'redis', 'nginx', 'postgres', 'mongodb', 'mysql'}
                for svc_name in services:
                    if svc_name not in skip:
                        return svc_name
            except Exception:
                pass
    return 'app'  # default fallback


def parse_tasks_to_backlog(tasks_text: str) -> list[dict]:
    """Parse task list into backlog items."""
    items, task_num = [], 0
    for line in tasks_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- [") or re.match(r'^\d+\.', stripped):
            task_num += 1
            desc = re.sub(r'^-\s*\[\s*\]\s*', '', stripped)
            desc = re.sub(r'^\d+\.\s*', '', desc)
            items.append({"id": task_num, "description": desc.strip(), "status": "pending"})
    if not items:
        items.append({"id": 1, "description": "Implement feature", "status": "pending"})
    return items


def generate_backlog_md(items: list[dict], project_folder: str) -> str:
    """Generate backlog.md markdown."""
    lines = ["# Implementation Backlog", "", f"Project: {project_folder}", ""]
    lines.append("| ID | Description | Status |")
    lines.append("|----|-------------|--------|")
    for item in items:
        lines.append(f"| {item['id']} | {item['description'][:60]} | {item['status']} |")
    lines.extend(["", "---", "*Generated by Loop Engineering BUILD phase*"])
    return "\n".join(lines)


def extract_data_models(docker_proj: str) -> list[dict]:
    """Extract data models from project code."""
    models = []
    p = Path(docker_proj) / "app" / "models"
    if not p.exists():
        return models
    for pyfile in p.glob("*.py"):
        if pyfile.name.startswith("_"):
            continue
        text = pyfile.read_text(errors="replace")
        for match in re.finditer(
            r'class\s+(\w+)\s*\([^)]*(?:Base|Model|DeclarativeBase)[^)]*\)', text,
        ):
            model_name = match.group(1)
            fields = re.findall(
                rf'(?:class\s+{model_name}\s*\([^)]*\)[^:]*:|class\s+{model_name}.*?)(.*?)(\n\nclass|\Z)',
                text, re.DOTALL,
            )
            field_list = []
            for _, block in fields:
                for fname, ftype in re.findall(r'(\w+)\s*:\s*(\w+)', block):
                    field_list.append({"name": fname, "type": ftype})
            models.append({"name": model_name, "file": str(pyfile.relative_to(Path(docker_proj))), "fields": field_list})
    return models


def extract_api_specs(docker_proj: str) -> list[dict]:
    """Extract API specs from route files."""
    specs = []
    p = Path(docker_proj)
    for router_dir in [p / "app" / "api", p / "app" / "routers"]:
        if not router_dir.exists():
            continue
        for pyfile in router_dir.glob("*.py"):
            if pyfile.name.startswith("_"):
                continue
            for method, path in re.findall(
                r'@\w+\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
                pyfile.read_text(errors="replace"),
            ):
                specs.append({"method": method.upper(), "path": path, "file": str(pyfile.relative_to(p))})
    return specs


def parse_uat_pass_rate(uat_output: str) -> float:
    """Parse UAT pass rate from text output. Returns 0.0-1.0."""
    if not uat_output:
        return 0.5
    output_lower = uat_output.lower()
    if "pass" in output_lower and "fail" not in output_lower:
        return 1.0
    if "fail" in output_lower and "pass" not in output_lower:
        return 0.0
    match = re.search(r'(\d+)\s*passed.*?(\d+)\s*failed', output_lower)
    if match:
        passed, failed = int(match.group(1)), int(match.group(2))
        total = passed + failed
        return passed / total if total > 0 else 0.5
    match = re.search(r'pass[\s_-]?rate[:\s=]+([\d.]+)', output_lower)
    if match:
        rate = float(match.group(1))
        return min(rate, 1.0) if rate <= 1.0 else min(rate / 100.0, 1.0)
    match = re.search(r'(\d+(?:\.\d+)?)\s*%', output_lower)
    if match:
        return min(float(match.group(1)) / 100.0, 1.0)
    pass_count = len(re.findall(r'\[pass\]', output_lower))
    fail_count = len(re.findall(r'\[fail\]', output_lower))
    total = pass_count + fail_count
    return pass_count / total if total > 0 else 0.5


def resolve_service_name(docker_proj: str) -> str:
    """Dynamically resolve the application service name from docker-compose.yml.

    The generated compose file can name the app service differently (e.g., 'app',
    'api', 'web'). This function inspects the actual file and returns the correct
    service name so docker compose commands don't fail with 'no such service'.

    Falls back to 'api' if no compose file is found or no services can be read.
    """
    import subprocess as _sp

    for candidate in [docker_proj, os.path.join(docker_proj, "")]:
        for pattern in ['docker-compose.yml', 'docker-compose.yaml', 'compose.yml', 'compose.yaml']:
            compose_file = os.path.join(candidate, pattern)
            if os.path.exists(compose_file):
                try:
                    result = _sp.run(
                        ['docker', 'compose', '-f', compose_file, 'ls', '--format', 'json'],
                        capture_output=True, text=True, timeout=10, cwd=docker_proj,
                    )
                    if result.returncode == 0 and result.stdout:
                        import json as _json
                        for svc in _json.loads(result.stdout.strip()):
                            name = svc.get('Name', '')
                            if name in ('api', 'app', 'web', 'backend'):
                                return name
                except Exception:
                    pass
                # Fallback: parse YAML directly
                try:
                    with open(compose_file) as f:
                        content = f.read()
                    # Simple YAML service extraction
                    import yaml as _yaml
                    data = _yaml.safe_load(content)
                    if data and 'services' in data:
                        for svc_name in data['services']:
                            if svc_name in ('api', 'app', 'web', 'backend'):
                                return svc_name
                        # If none of the well-known names, take the non-db one
                        for svc_name in data['services']:
                            if svc_name not in ('db', 'database', 'redis', 'nginx', 'worker'):
                                return svc_name
                except Exception:
                    pass
                break  # found compose file, no need to check other patterns

    # Ultimate fallback
    return 'api'


def parse_uat_metrics(uat_output: str) -> dict:
    """Parse UAT metrics: pass_rate, latency_ms, flakiness."""
    uat_pass = parse_uat_pass_rate(uat_output)
    latency_ms = 0.0
    ms_matches = re.findall(r'(\d+(?:\.\d+)?)\s*ms', uat_output)
    if ms_matches:
        latency_ms = max(float(x) for x in ms_matches)
    else:
        sec_matches = re.findall(r'(\d+(?:\.\d+)?)\s*(?:sec|seconds|s)\b', uat_output)
        if sec_matches:
            latency_ms = max(float(x) for x in sec_matches) * 1000
    output_lower = uat_output.lower()
    retry_count = len(re.findall(r'retry|retried|intermittent|flaky|inconsistent|sometimes\s+fail', output_lower))
    total_checks = len(re.findall(r'\[(?:pass|fail)\]', output_lower))
    flakiness = min(retry_count / total_checks, 1.0) if total_checks > 0 else min(retry_count * 0.1, 1.0)
    return {"uat_pass_rate": uat_pass, "latency_ms": latency_ms, "test_flakiness_rate": flakiness}
