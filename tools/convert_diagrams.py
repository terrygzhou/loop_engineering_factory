#!/usr/bin/env python3
"""Convert Mermaid .mmd files to PNG using Playwright."""
import asyncio
import re
from pathlib import Path
from playwright.async_api import async_playwright

# Local mermaid.min.js bundle — resolves relative to this file (works in Docker).
_MERMAID_JS = Path(__file__).resolve().parent.parent / "frontend" / "static" / "js" / "mermaid.min.js"

if not _MERMAID_JS.exists():
    import warnings
    warnings.warn(f"Local mermaid bundle not found at {_MERMAID_JS} — diagram PNG conversion will fail")


def extract_mermaids(text: str) -> list[str]:
    """Extract all mermaid blocks from a markdown file, returning a list of content strings."""
    blocks: list[str] = []
    for match in re.finditer(r'```mermaid\n(.*?)```', text, re.DOTALL):
        content = match.group(1).strip()
        if content:
            blocks.append(content)
    if not blocks:
        # Fallback: grab everything after the first ```mermaid line
        lines = text.split('\n')
        start = 0
        for i, line in enumerate(lines):
            if line.startswith('```mermaid'):
                start = i + 1
                break
        if start > 0:
            return ['\n'.join(lines[start:]).strip()]
    return blocks


# Backwards-compatible alias — returns first block only (kept for callers that expect a single string).
def extract_mermaid(text: str) -> str:
    """Extract first mermaid content from markdown file (backwards-compatible)."""
    blocks = extract_mermaids(text)
    return blocks[0] if blocks else text


def make_html(mmd_content: str) -> str:
    """Create standalone HTML with local Mermaid JS bundle."""
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False)
    tmp.write(f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="file://{_MERMAID_JS.resolve()}"></script>
</head>
<body>
<pre class="mermaid">{mmd_content}</pre>
<script>
mermaid.initialize({{startOnLoad: true}});
</script>
</body>
</html>
""")
    tmp.close()
    return tmp.name


async def convert_mmd_to_png(mmd_path: Path, png_path: Path):
    """Convert a single .mmd file to PNG (renders first mermaid block for backwards compat)."""
    content = mmd_path.read_text()
    mermaid_content = extract_mermaid(content)

    tmp_html_path = make_html(mermaid_content)
    tmp_html = Path(tmp_html_path)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 1000})
        await page.goto(f"file://{tmp_html.resolve()}")
        await page.wait_for_timeout(5000)
        await page.screenshot(path=str(png_path), full_page=False)
        await browser.close()

    tmp_html.unlink()
    return png_path


async def convert_mmd_to_pngs(mmd_path: Path, output_dir: Path, prefix: str) -> list[str]:
    """Convert all mermaid blocks in a .mmd file to separate numbered PNGs."""
    content = mmd_path.read_text()
    blocks = extract_mermaids(content)
    if not blocks:
        return []

    tmp_htmls: list[Path] = []
    png_paths: list[Path] = []
    for idx, block in enumerate(blocks, 1):
        name = f"{prefix}-{idx}.png" if len(blocks) > 1 else f"{prefix}.png"
        png_paths.append(output_dir / name)
        tmp_htmls.append(Path(make_html(block)))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 1000})
        for tmp_html, png_path in zip(tmp_htmls, png_paths):
            await page.goto(f"file://{tmp_html.resolve()}")
            await page.wait_for_timeout(5000)
            await page.screenshot(path=str(png_path), full_page=False)
        await browser.close()

    for tmp_html in tmp_htmls:
        tmp_html.unlink()

    return [str(p) for p in png_paths]


async def convert_all_diagrams(diagrams_dir: Path):
    """Convert all .mmd files in a directory to PNG (handles multiple blocks per file)."""
    results: dict[str, list[str]] = {}
    for mmd_file in diagrams_dir.glob("*.mmd"):
        try:
            pngs = await convert_mmd_to_pngs(mmd_file, diagrams_dir, mmd_file.stem)
            results[mmd_file.stem] = pngs
            for png in pngs:
                print(f"  ✓ {mmd_file.name} → {Path(png).name}")
        except Exception as e:
            print(f"  ✗ {mmd_file.name}: {e}")
            results[mmd_file.stem] = []
    return results


if __name__ == "__main__":
    import sys, os
    diagrams_dir = Path(sys.argv[1])

    results: dict[str, list[str]] = {}
    for mmd_file in diagrams_dir.glob("*.mmd"):
        try:
            pngs = asyncio.run(convert_mmd_to_pngs(mmd_file, diagrams_dir, mmd_file.stem))
            results[mmd_file.stem] = pngs
            for png in pngs:
                print(f"  ✓ {mmd_file.name} → {Path(png).name}")
        except PermissionError:
            # Root-owned dir — write to user temp instead
            import tempfile
            tmp_dir = Path(tempfile.mkdtemp())
            pngs = asyncio.run(convert_mmd_to_pngs(mmd_file, tmp_dir, mmd_file.stem))
            results[mmd_file.stem] = pngs
            for png in pngs:
                print(f"  ⚠ {mmd_file.name} → {Path(png).name} (temp, root-owned dir)")
        except Exception as e:
            print(f"  ✗ {mmd_file.name}: {e}")
            results[mmd_file.stem] = []
    total = sum(len(v) for v in results.values())
    print(f"\nConverted {total}/{len(results)} files ({total} PNGs)")