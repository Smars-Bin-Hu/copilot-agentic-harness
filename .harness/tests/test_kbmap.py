"""The repository map (M15-10d): the extractors, `kb map`, `kb near` and `kb split` on a made-up SQL Server repository."""

from __future__ import annotations

import json
import unittest

from support import HarnessTestCase
from test_targets import GIT, make_repo, run_git

from core import kbextract, kbmap

LOAD_ORDERS = """SET ANSI_NULLS ON
GO
CREATE PROCEDURE [dbo].[usp_load_orders] AS
BEGIN
  -- reads dbo.not_this_one
  /* EXEC dbo.not_called */
  WITH recent AS (SELECT * FROM dbo.stg_orders s JOIN dbo.calendar c ON c.d = s.d)
  MERGE INTO dbo.orders AS t USING recent AS r ON t.id = r.id
  WHEN MATCHED THEN UPDATE SET t.x = r.x;
  UPDATE o SET o.flag = 1 FROM dbo.orders o JOIN dbo.stg_orders s ON s.id = o.id;
  EXEC dbo.usp_log 'loaded orders from dbo.fake';
  SELECT 'x' AS a INTO #tmp;
END
GO
"""

PUBLISH = """CREATE PROC dbo.usp_publish_summary AS
TRUNCATE TABLE dbo.summary;
INSERT dbo.summary SELECT o.id, r.rate FROM dbo.orders o JOIN Other.dbo.rates r ON r.id = o.id;
EXEC dbo.usp_log;
DECLARE @s nvarchar(max) = N'select 1';
EXEC sp_executesql @s;
"""


def job(name: str, *steps: str) -> str:
    lines = ["BEGIN TRANSACTION", "DECLARE @ReturnCode INT", f"EXEC @ReturnCode = msdb.dbo.sp_add_job @job_name=N'{name}', @enabled=1"]
    lines += steps
    lines.append("EXEC @ReturnCode = msdb.dbo.sp_add_jobschedule @job_id=@jobId, @name=N'nightly'")
    return "\n".join(lines) + "\nCOMMIT TRANSACTION\n"


def tsql_step(command: str) -> str:
    return f"EXEC @ReturnCode = msdb.dbo.sp_add_jobstep @job_id=@jobId, @step_name=N'step', @subsystem=N'TSQL', @command=N'{command}', @database_name=N'Shop'"


SSIS_STEP = """EXEC @ReturnCode = msdb.dbo.sp_add_jobstep @job_id=@jobId, @step_name=N'publish', @subsystem=N'SSIS', @command=N'/ISSERVER "\\"\\SSISDB\\Shop\\ShopEtl\\Publish.dtsx\\"" /SERVER "\\"srv\\""'"""

PACKAGE = """<?xml version="1.0"?>
<DTS:Executable xmlns:DTS="www.microsoft.com/SqlServer/Dts" DTS:ObjectName="Publish">
  <DTS:Executables>
    <DTS:Executable DTS:ObjectName="Run summary"><DTS:ObjectData>
      <SQLTask:SqlTaskData SQLTask:SqlStatementSource="EXEC dbo.usp_publish_summary" xmlns:SQLTask="www.microsoft.com/sqlserver/dts/tasks/sqltask" />
    </DTS:ObjectData></DTS:Executable>
    <DTS:Executable DTS:ObjectName="Copy"><DTS:ObjectData><pipeline><components>
      <component componentClassID="Microsoft.OLEDBSource" name="src"><properties><property name="OpenRowset">[dbo].[summary]</property></properties></component>
      <component componentClassID="Microsoft.OLEDBDestination" name="dst"><properties><property name="OpenRowset">[dbo].[export_summary]</property></properties></component>
    </components></pipeline></DTS:ObjectData></DTS:Executable>
    <DTS:Executable DTS:ObjectName="Child"><DTS:ObjectData><ExecutePackageTask><UseProjectReference>True</UseProjectReference><PackageName>Child.dtsx</PackageName></ExecutePackageTask></DTS:ObjectData></DTS:Executable>
  </DTS:Executables>
</DTS:Executable>
"""


def table(name: str) -> str:
    return f"CREATE TABLE [dbo].[{name}] (id int NOT NULL)\nGO\n"


FILES = {
    "Shop/Shop.sqlproj": "<Project />\n",
    **{f"Shop/dbo/Tables/{name}.sql": table(name) for name in ("orders", "stg_orders", "summary", "calendar", "customers", "stg_customers", "log")},
    "Shop/dbo/Stored Procedures/usp_load_orders.sql": LOAD_ORDERS,
    "Shop/dbo/Stored Procedures/usp_publish_summary.sql": PUBLISH,
    "Shop/dbo/Stored Procedures/usp_load_customers.sql": "CREATE PROCEDURE dbo.usp_load_customers AS\nINSERT INTO dbo.customers SELECT * FROM dbo.stg_customers s JOIN dbo.calendar c ON c.d = s.d;\nEXEC dbo.usp_log;\n",
    "Shop/dbo/Stored Procedures/usp_log.sql": "CREATE PROCEDURE dbo.usp_log @what nvarchar(200) = NULL AS\nINSERT INTO dbo.log (what) VALUES (@what);\n",
    "Shop/dbo/Stored Procedures/usp_unused.sql": "CREATE PROCEDURE dbo.usp_unused AS\nSELECT 1 FROM dbo.log;\n",
    "jobs/Shop_Orders.sql": job("Shop_Orders", tsql_step("EXEC dbo.usp_load_orders"), SSIS_STEP),
    "jobs/Shop_Customers.sql": job("Shop_Customers", tsql_step("EXEC dbo.usp_load_customers")),
    "jobs/Shop_Audit.sql": job("Shop_Audit", tsql_step("EXEC dbo.usp_log; SELECT * FROM dbo.calendar;")),
    "ShopEtl/ShopEtl.dtproj": "<Project />\n",
    "ShopEtl/Publish.dtsx": PACKAGE,
    "ShopEtl/Child.dtsx": "<?xml version=\"1.0\"?>\n<DTS:Executable xmlns:DTS=\"www.microsoft.com/SqlServer/Dts\" />\n",
    "README.md": "x\n",
}


class ExtractTests(unittest.TestCase):
    def objects(self, text: str, db: str = "Shop") -> dict:
        return {item["id"]: item for item in kbextract.tsql(text, {"db": db, "path": "a.sql"})}

    def uses(self, item: dict) -> set:
        return {(ref["kind"], ref["name"]) for ref in item["refs"]}

    def test_a_procedure_and_what_it_reads_writes_and_calls(self) -> None:
        found = self.objects(LOAD_ORDERS)
        self.assertEqual(list(found), ["sp:Shop.dbo.usp_load_orders"])
        item = found["sp:Shop.dbo.usp_load_orders"]
        self.assertEqual(item["line"], 3)
        self.assertEqual(self.uses(item), {
            ("reads", "dbo.stg_orders"), ("reads", "dbo.calendar"), ("reads", "dbo.orders"),
            ("writes", "dbo.orders"), ("calls", "dbo.usp_log"),
        })
        self.assertFalse(item["dynamic"])

    def test_names_in_comments_strings_ctes_and_temp_tables_are_not_uses(self) -> None:
        names = {name for _kind, name in self.uses(self.objects(LOAD_ORDERS)["sp:Shop.dbo.usp_load_orders"])}
        for left_out in ("dbo.not_this_one", "dbo.not_called", "dbo.fake", "recent", "#tmp"):
            self.assertNotIn(left_out, names)

    def test_sql_known_only_at_run_time_is_marked(self) -> None:
        item = self.objects(PUBLISH)["sp:Shop.dbo.usp_publish_summary"]
        self.assertTrue(item["dynamic"])
        self.assertIn(("writes", "dbo.summary"), self.uses(item))
        self.assertIn(("reads", "Other.dbo.rates"), self.uses(item))

    def test_a_script_saved_as_utf16(self) -> None:
        data = b"\xff\xfe" + table("t").encode("utf-16-le")
        self.assertEqual([item["id"] for item in kbextract.extract("tsql", data, {"db": "", "path": "t.sql"})], ["table:dbo.t"])

    def test_a_job_script_runs_a_procedure_and_a_package(self) -> None:
        found = kbextract.tsql(FILES["jobs/Shop_Orders.sql"], {"db": "", "path": "j.sql"})
        self.assertEqual([item["id"] for item in found], ["job:Shop_Orders"])
        self.assertTrue(found[0]["scheduled"])
        self.assertEqual(self.uses(found[0]), {("calls", "dbo.usp_load_orders"), ("runs", "ShopEtl/Publish")})
        self.assertEqual(found[0]["refs"][0]["db"], "Shop")

    def test_a_package(self) -> None:
        found = kbextract.ssis(PACKAGE, {"stem": "Publish", "project": "ShopEtl", "path": "p.dtsx"})
        self.assertEqual(found[0]["id"], "package:ShopEtl/Publish")
        self.assertEqual(self.uses(found[0]), {
            ("calls", "dbo.usp_publish_summary"), ("reads", "[dbo].[summary]"), ("writes", "[dbo].[export_summary]"), ("runs", "Child"),
        })

    def test_a_broken_file_gives_nothing_and_does_not_stop(self) -> None:
        self.assertEqual(kbextract.extract("ssis", b"<not xml", {"stem": "x", "project": "", "path": "x.dtsx"})[0]["dynamic"], True)
        self.assertEqual(kbextract.extract("tsql", b"\x00\x01garbage", {"db": "", "path": "x.sql"}), [])

    def test_rules_of_a_profile(self) -> None:
        rule = {"node": {"type": "class", "pattern": r"class\s+(\w+)"}, "edges": [{"kind": "uses", "pattern": r"^import\s+[\w.]*\.(\w+);", "as": "class"}]}
        found = kbextract.regex("import a.b.Repo;\npublic class Service {}\n", {"path": "S.java", "rule": rule})
        self.assertEqual(found[0]["id"], "class:Service")
        self.assertEqual(found[0]["refs"][0]["name"], "Repo")


@unittest.skipUnless(GIT, "git is not installed")
class MapTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        repos = self.root / "source" / "repos"
        self.repo = make_repo(repos / "repo_a", FILES)
        (self.root / ".harness" / "policies" / "target.override.json").write_text(json.dumps({"repos_root": str(repos)}), encoding="utf-8")

    def build(self, **options) -> dict:
        return kbmap.build(self.root, **options)

    def test_the_map_finds_the_objects_and_their_uses(self) -> None:
        result = self.build()
        self.assertEqual(result["mapped"][0]["profile"], "sqlserver")
        self.assertEqual(result["objects"], {"job": 3, "package": 2, "sp": 5, "table": 7})
        self.assertEqual(result["entry_points"], 3)
        self.assertEqual(result["unused_sample"], ["sp:Shop.dbo.usp_unused"])
        self.assertEqual(result["dynamic_sample"], ["sp:Shop.dbo.usp_publish_summary"])
        self.assertEqual({item["name"] for item in result["external"]}, {"Other.dbo.rates", "dbo.export_summary"})
        self.assertEqual(result["most_used"][0]["id"], "sp:Shop.dbo.usp_log")

    def test_only_changed_files_are_read_again(self) -> None:
        self.assertEqual(self.build()["mapped"][0]["read"], 17)
        self.assertEqual(self.build()["mapped"][0]["read"], 0)
        (self.repo / "Shop" / "dbo" / "Stored Procedures" / "usp_unused.sql").write_text("CREATE PROCEDURE dbo.usp_unused AS\nEXEC dbo.usp_log;\n", encoding="utf-8")
        run_git(self.repo, "commit", "-qam", "change")
        self.assertEqual(self.build()["mapped"][0]["read"], 1)
        self.assertEqual(self.build(fresh=True)["mapped"][0]["read"], 17)

    def test_near_walks_both_ways_across_the_job_the_package_and_the_procedure(self) -> None:
        self.build()
        result = kbmap.near(self.root, "summary", depth=3, direction="up")
        self.assertEqual(result["id"], "table:Shop.dbo.summary")
        found = {(row["id"], row["how"]) for row in result["used_by"]}
        self.assertIn(("sp:Shop.dbo.usp_publish_summary", "writes"), found)
        self.assertIn(("package:ShopEtl/Publish", "reads"), found)
        self.assertIn(("job:Shop_Orders", "runs"), found)
        down = kbmap.near(self.root, "job:Shop_Orders", depth=1, direction="down")
        self.assertEqual({row["id"] for row in down["uses"]}, {"sp:Shop.dbo.usp_load_orders", "package:ShopEtl/Publish"})

    def test_near_with_a_name_that_fits_several(self) -> None:
        self.build()
        self.assertGreater(len(kbmap.near(self.root, "usp_load")["matches"]), 1)
        with self.assertRaises(kbmap.MapError):
            kbmap.near(self.root, "nothing_like_it")

    def test_split_takes_out_what_every_job_uses_then_cuts_by_entry_point(self) -> None:
        self.build()
        result = kbmap.split(self.root)
        self.assertEqual({item["id"] for item in result["shared"]}, {"sp:Shop.dbo.usp_log", "table:Shop.dbo.log", "table:Shop.dbo.calendar"})
        groups = {tuple(item["entry_points"]): item for item in result["domains"]}
        self.assertEqual(set(groups), {("job:Shop_Orders",), ("job:Shop_Customers",), ("job:Shop_Audit",)})
        self.assertEqual(groups[("job:Shop_Orders",)]["types"], {"job": 1, "package": 2, "sp": 2, "table": 3})
        self.assertIn("orders", groups[("job:Shop_Orders",)]["name_hint"])
        self.assertEqual(result["unreached_sample"], ["sp:Shop.dbo.usp_unused"])
        self.assertNotIn("note", result)

    def test_a_high_bar_for_shared_joins_everything(self) -> None:
        self.build()
        result = kbmap.split(self.root, shared_min=9)
        self.assertEqual(len(result["domains"]), 1)
        self.assertIn("note", result)

    def test_no_profile_fits(self) -> None:
        make_repo(self.root / "source" / "repos" / "repo_b", {"notes.txt": "hello\n"})
        rows = {row["repo"]: row for row in self.build()["mapped"]}
        self.assertEqual(rows["repo_b"]["profile"], "-")
        self.assertIn("note", rows["repo_b"])

    def test_the_commands(self) -> None:
        self.assertEqual(self.cli_json("kb", "map", "--json")["entry_points"], 3)
        near = self.cli_json("kb", "near", "usp_log", "--up", "--json")
        self.assertEqual(near["id"], "sp:Shop.dbo.usp_log")
        self.assertNotIn("uses", near)
        self.assertEqual(len(self.cli_json("kb", "split", "--json")["domains"]), 3)
        done = self.cli("kb", "near", "nothing_like_it")
        self.assertNotEqual(done.returncode, 0)

    def test_no_map_yet(self) -> None:
        with self.assertRaises(kbmap.MapError):
            kbmap.split(self.root)

    def test_a_team_profile_in_the_knowledge_base_wins(self) -> None:
        folder = self.root / "knowledge-base" / "profiles"
        folder.mkdir(parents=True)
        mine = json.loads((self.root / kbmap.PROFILES / "sqlserver.json").read_text(encoding="utf-8"))
        mine["ignore"] = ["jobs/**"]
        (folder / "sqlserver.json").write_text(json.dumps(mine), encoding="utf-8")
        self.assertNotIn("job", self.build()["objects"])


if __name__ == "__main__":
    unittest.main()
