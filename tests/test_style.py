"""House style for every Python file; see the Style section of AGENTS.md."""
import ast
import io
from pathlib import Path
import re
import tokenize
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILES = (sorted((ROOT / "danus_rsi").glob("*.py")) + sorted((ROOT / "tests").glob("*.py"))
         + [ROOT / "scripts" / "check.py"])
TRIVIAL = {"__init__.py", "__main__.py"}
MAX_LINE = 120


def imported_names(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from ((alias.asname or alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            yield from (alias.asname or alias.name for alias in node.names)


def used_names(tree):
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def import_blocks(tree):
    """Top-level import statements grouped into runs of consecutive lines."""
    blocks, last = [], None
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            if blocks and last is not None:
                last = None
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        module = node.names[0].name if isinstance(node, ast.Import) else "." * node.level + (node.module or "")
        if last is None or node.lineno != last + 1:
            blocks.append([])
        blocks[-1].append(module)
        last = node.end_lineno
    return blocks


class StyleTests(unittest.TestCase):
    def test_lines_whitespace_and_final_newline(self):
        for path in FILES:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertTrue(text.endswith("\n") and not text.endswith("\n\n"), "file must end with one newline")
                for number, line in enumerate(text.splitlines(), 1):
                    self.assertLessEqual(len(line), MAX_LINE, f"line {number} is longer than {MAX_LINE}")
                    self.assertNotIn("\t", line, f"tab on line {number}")
                    self.assertEqual(line, line.rstrip(), f"trailing whitespace on line {number}")

    def test_module_header(self):
        for path in FILES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            with self.subTest(path=path.name):
                if path.parent.name == "danus_rsi" and path.name not in TRIVIAL:
                    self.assertIsNotNone(ast.get_docstring(tree), "module docstring")
                    self.assertTrue(any(isinstance(n, ast.ImportFrom) and n.module == "__future__" for n in tree.body),
                                    "from __future__ import annotations")

    def test_imports_used_grouped_and_sorted(self):
        for path in FILES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            with self.subTest(path=path.name):
                unused = sorted(set(imported_names(tree)) - used_names(tree)
                                - {n.value.id for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                                   and isinstance(n.value, ast.Name)})
                self.assertEqual(unused, [], "unused imports")
                for block in import_blocks(tree):
                    keys = [m.lstrip(".").lower() for m in block]
                    self.assertEqual(keys, sorted(keys), "imports sorted by module name within a block")

    def test_two_blank_lines_between_top_level_definitions(self):
        for path in FILES:
            lines = path.read_text(encoding="utf-8").splitlines()
            tree = ast.parse("\n".join(lines))
            defs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))]
            with self.subTest(path=path.name):
                for node in defs:
                    start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
                    while start > 0 and lines[start - 1].startswith("#"):
                        start -= 1  # a comment block belongs to the definition below it
                    if start == 0 or node is tree.body[0]:
                        continue
                    self.assertEqual(lines[start - 2:start], ["", ""], f"two blank lines before line {start + 1}")

    def test_double_quotes(self):
        # Python 3.11 cannot reuse the outer quote inside an f-string expression, so strings
        # nested in f-strings (tokenized separately from Python 3.12) may be single-quoted.
        fstring_start, fstring_end = getattr(tokenize, "FSTRING_START", None), getattr(tokenize, "FSTRING_END", None)
        for path in FILES:
            tokens = tokenize.generate_tokens(io.StringIO(path.read_text(encoding="utf-8")).readline)
            with self.subTest(path=path.name):
                depth = 0
                for token in tokens:
                    depth += (token.type == fstring_start) - (token.type == fstring_end)
                    if token.type == tokenize.STRING and not depth:
                        body = re.sub(r"^[rRbBuUfF]*", "", token.string)
                        if body.startswith("'") and '"' not in body:
                            self.fail(f"single-quoted string on line {token.start[0]}: {token.string[:40]}")


if __name__ == "__main__":
    unittest.main()
