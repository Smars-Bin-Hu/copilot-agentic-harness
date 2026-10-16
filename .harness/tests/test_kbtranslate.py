"""The check script of generic-kb-translate (M15-9): a translation keeps the structure and follows the glossary."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "skills" / "generic-kb-translate" / "scripts" / "kbtranslate.py"
spec = importlib.util.spec_from_file_location("kbtranslate", SCRIPT)
kbtranslate = importlib.util.module_from_spec(spec)
sys.dont_write_bytecode, before = True, sys.dont_write_bytecode  # no __pycache__ left in the skill folder
spec.loader.exec_module(kbtranslate)  # type: ignore[union-attr]
sys.dont_write_bytecode = before

ORIGINAL = """# 订单加载

每天凌晨做**增量加载**，读取 `stg.orders`，详见 [说明](docs/load.md)。

| 字段 | 含义 |
| --- | --- |
| order_id | 订单号 |

```sql
-- 取昨天的数据
select * from stg.orders where dt = @d;
```
"""

GOOD = """# Order load

The **incremental load** runs early every morning. It reads `stg.orders`. See [the notes](docs/load.md).

| Field | Meaning |
| --- | --- |
| order_id | order number |

```sql
-- take yesterday's data
select * from stg.orders where dt = @d;
```
"""

GLOSSARY = """| 中文 | English | Note |
| --- | --- | --- |
| 增量加载 | incremental load | |
"""


class CheckTests(unittest.TestCase):
    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.task = Path(holder.name) / "job"
        (self.task / ".task" / "base" / "kb").mkdir(parents=True)
        (self.task / "DEV" / "kb").mkdir(parents=True)
        (self.task / ".task" / "base" / "kb" / "a.md").write_text(ORIGINAL, encoding="utf-8")
        self.glossary = self.task / "glossary.md"
        self.glossary.write_text(GLOSSARY, encoding="utf-8")

    def run_check(self, translated: str) -> str:
        (self.task / "DEV" / "kb" / "a.md").write_text(translated, encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.code = kbtranslate.main(["check", "--task", str(self.task), "--glossary", str(self.glossary)])
        return out.getvalue()

    def test_a_faithful_translation_passes(self) -> None:
        said = self.run_check(GOOD)
        self.assertEqual(self.code, 0, said)

    def test_each_kind_of_damage_is_named(self) -> None:
        cases = {
            "headings differ": GOOD.replace("# Order load", "Order load"),
            "tables differ": GOOD.replace("| order_id | order number |\n", ""),
            "code block 1": GOOD.replace("where dt = @d", "where dt = @day"),
            "inline code changed": GOOD.replace("`stg.orders`", "the orders table"),
            "link targets changed": GOOD.replace("docs/load.md", "docs/load-en.md"),
            "Chinese left": GOOD.replace("order number", "订单号"),
            "glossary": GOOD.replace("incremental load", "delta load"),
        }
        for expected, translated in cases.items():
            said = self.run_check(translated)
            self.assertEqual(self.code, 1, expected)
            self.assertIn(expected, said, expected)

    def test_yaml_keys_stay(self) -> None:
        (self.task / ".task" / "base" / "kb" / "d.yaml").write_text("name: 订单\nowner: 数据组\n", encoding="utf-8")
        (self.task / "DEV" / "kb" / "d.yaml").write_text("名字: orders\nowner: data team\n", encoding="utf-8")
        said = self.run_check(GOOD)
        self.assertIn("keys changed", said)

    def test_terms_lists_the_heading_and_table_words_first(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            kbtranslate.main(["terms", "--task", str(self.task)])
        first = out.getvalue().splitlines()[0].split("\t")
        self.assertTrue(first[2])
