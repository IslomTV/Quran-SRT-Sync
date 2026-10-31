import json
import tempfile
import unittest
from pathlib import Path

import app
from fastapi import HTTPException
from core.capcut_timing import apply_preview, create_preview


class TestCapCutTiming(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.projects_dir = self.root / "projects"
        self.srt_dir = self.root / "arabic"
        self.project_dir = self.projects_dir / "1. Fotiha - الفاتحة"
        self.project_dir.mkdir(parents=True)
        self.srt_dir.mkdir()
        self.draft_path = self.project_dir / "draft_content.json"
        self.srt_path = self.srt_dir / "1_arabic.srt"
        self._write_project()
        self._write_srt()

    def tearDown(self):
        app.CAPCUT_PREVIEWS.clear()
        self.temp_dir.cleanup()

    def test_api_preview_defaults_to_exact_srt_behavior(self):
        request = app.CapCutPreviewRequest(
            projects_dir=str(self.projects_dir),
            srt_dir=str(self.srt_dir),
        )

        self.assertTrue(request.allow_overlaps)
        self.assertTrue(request.extend_project_duration)

    def test_preview_starts_from_projects_and_ignores_unmatched_srts(self):
        (self.srt_dir / "99_arabic.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nUnmatched SRT\n",
            encoding="utf-8",
        )

        preview = create_preview(self.srt_dir, self.projects_dir)

        self.assertEqual(list(preview.plans), ["1"])
        self.assertEqual(preview.issues, [])

    def test_preview_reports_project_without_srt(self):
        (self.projects_dir / "2. Project without SRT").mkdir()
        (self.srt_dir / "99_arabic.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nUnmatched SRT\n",
            encoding="utf-8",
        )

        preview = create_preview(self.srt_dir, self.projects_dir)

        self.assertEqual(list(preview.plans), ["1"])
        self.assertEqual(
            preview.issues,
            ["2. Project without SRT: no matching Arabic SRT file beginning with 2"],
        )

    def _write_srt(self, first_text="بِسْمِ اللَّهِ", second_text="الْحَمْدُ لِلَّهِ"):
        self.srt_path.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\n"
            f"{first_text}\n\n"
            "2\n00:00:02,000 --> 00:00:05,000\n"
            f"{second_text}\n",
            encoding="utf-8",
        )

    def _write_project(self, duration=4_000_000):
        texts = [
            {"id": "intro", "type": "subtitle", "content": json.dumps({"text": "أعوذ بالله"})},
            {"id": "ayah-1", "type": "subtitle", "content": json.dumps({"text": "بِسْمِ اللَّهِ"})},
            {"id": "ayah-2", "type": "subtitle", "content": json.dumps({"text": "الْحَمْدُ لِلَّهِ"})},
        ]
        segments = [
            {"material_id": "intro", "target_timerange": {"start": 0, "duration": 1_000_000}},
            {"material_id": "ayah-1", "target_timerange": {"start": 1_000_000, "duration": 1_000_000}},
            {"material_id": "ayah-2", "target_timerange": {"start": 2_000_000, "duration": 1_000_000}},
        ]
        self.draft_path.write_text(
            json.dumps({
                "duration": duration,
                "materials": {"texts": texts},
                "tracks": [{"type": "text", "segments": segments}],
            }, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_preview_defaults_to_approved_overlap_and_duration_behavior(self):
        preview = create_preview(self.srt_dir, self.projects_dir)
        plan = preview.plans["1"]

        self.assertEqual(len(plan.srt_subtitles), 2)
        self.assertEqual(len(plan.capcut_subtitles), 3)
        self.assertEqual(plan.mapping, [(0, (1,)), (1, (2,))])
        self.assertTrue(plan.eligible)
        self.assertTrue(any("overlaps unmatched CapCut" in item for item in plan.warnings))
        self.assertTrue(any("beyond project duration" in item for item in plan.warnings))
        self.assertEqual(plan.extend_duration_to, 5_000_000)

    def test_apply_updates_matching_clips_preserves_extra_without_backup(self):
        preview = create_preview(
            self.srt_dir,
            self.projects_dir,
            allow_overlaps=True,
            extend_project_duration=True,
        )
        plan = preview.plans["1"]
        self.assertTrue(plan.eligible)

        result = apply_preview(preview, ["1"])

        updated = json.loads(self.draft_path.read_text(encoding="utf-8"))
        segments = updated["tracks"][0]["segments"]
        self.assertEqual(segments[0]["target_timerange"], {"start": 0, "duration": 1_000_000})
        self.assertEqual(segments[1]["target_timerange"], {"start": 0, "duration": 2_000_000})
        self.assertEqual(segments[2]["target_timerange"], {"start": 2_000_000, "duration": 3_000_000})
        self.assertEqual(updated["duration"], 5_000_000)
        self.assertNotIn("backup_path", result["updated"][0])
        self.assertFalse(self.draft_path.with_name("draft_content.json.bak").exists())
        self.assertEqual(result["updated"][0]["updated_subtitles"], 2)
        self.assertEqual(result["updated"][0]["updated_clips"], 2)
        self.assertEqual(result["errors"], [])

    def test_split_capcut_clips_match_combined_srt_text_and_keep_relative_split(self):
        project = json.loads(self.draft_path.read_text(encoding="utf-8"))
        materials = project["materials"]["texts"]
        materials[1]["content"] = json.dumps({"text": "بِسْمِ"})
        materials.insert(
            2,
            {
                "id": "ayah-1b",
                "type": "subtitle",
                "content": json.dumps({"text": "اللَّهِ"}),
            },
        )
        segments = project["tracks"][0]["segments"]
        segments[1]["target_timerange"] = {"start": 1_000_000, "duration": 1_000_000}
        segments.insert(
            2,
            {
                "material_id": "ayah-1b",
                "target_timerange": {"start": 2_000_000, "duration": 1_000_000},
            },
        )
        segments[3]["target_timerange"] = {"start": 3_000_000, "duration": 1_000_000}
        self.draft_path.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")

        preview = create_preview(self.srt_dir, self.projects_dir)
        plan = preview.plans["1"]

        self.assertTrue(plan.eligible)
        self.assertEqual(plan.mapping, [(0, (1, 2)), (1, (3,))])
        first_match = plan.to_dict()["matches"][0]
        self.assertEqual(first_match["capcut_indices"], [2, 3])
        self.assertEqual(first_match["split_count"], 2)
        self.assertEqual(plan.to_dict()["subtitle_counts"]["split_groups"], 1)

        result = apply_preview(preview, ["1"])

        updated = json.loads(self.draft_path.read_text(encoding="utf-8"))
        segments = updated["tracks"][0]["segments"]
        self.assertEqual(segments[1]["target_timerange"], {"start": 0, "duration": 1_000_000})
        self.assertEqual(segments[2]["target_timerange"], {"start": 1_000_000, "duration": 1_000_000})
        self.assertEqual(segments[3]["target_timerange"], {"start": 2_000_000, "duration": 3_000_000})
        self.assertEqual(result["updated"][0]["updated_clips"], 3)
        self.assertEqual(result["errors"], [])

    def test_ambiguous_clip_groups_block_split_match(self):
        project = json.loads(self.draft_path.read_text(encoding="utf-8"))
        materials = project["materials"]["texts"]
        materials.append(
            {"id": "ayah-1-duplicate", "type": "subtitle",
             "content": json.dumps({"text": "بِسْمِ اللَّهِ"})}
        )
        project["tracks"][0]["segments"].insert(
            2,
            {"material_id": "ayah-1-duplicate",
             "target_timerange": {"start": 2_500_000, "duration": 500_000}},
        )
        self.draft_path.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")

        preview = create_preview(self.srt_dir, self.projects_dir)
        plan = preview.plans["1"]

        self.assertFalse(plan.eligible)
        self.assertNotIn(0, {srt_index for srt_index, _ in plan.mapping})
        self.assertTrue(any("multiple CapCut clip groups match" in item for item in plan.blockers))
        self.assertEqual(plan.to_dict()["subtitle_counts"]["matched_capcut_clips"], 1)

    def test_api_resolves_only_user_selected_ambiguous_clip_group(self):
        project = json.loads(self.draft_path.read_text(encoding="utf-8"))
        materials = project["materials"]["texts"]
        materials.append(
            {"id": "ayah-1-duplicate", "type": "subtitle",
             "content": json.dumps({"text": "بِسْمِ اللَّهِ"})}
        )
        project["tracks"][0]["segments"].insert(
            2,
            {"material_id": "ayah-1-duplicate",
             "target_timerange": {"start": 1_500_000, "duration": 500_000}},
        )
        self.draft_path.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
        preview = create_preview(self.srt_dir, self.projects_dir)
        app.CAPCUT_PREVIEWS["manual-resolution-test"] = preview

        unresolved = preview.to_dict("manual-resolution-test")["projects"][0]
        self.assertEqual(unresolved["subtitle_counts"]["matched"], 1)
        self.assertEqual(
            unresolved["ambiguous_matches"][0]["candidates"],
            [[2], [3]],
        )
        resolved = app.resolve_capcut_matches(app.CapCutResolveRequest(
            preview_id="manual-resolution-test",
            resolutions=[
                app.CapCutMatchResolution(number="1", srt_index=1, capcut_indices=[2])
            ],
        ))

        project_result = resolved["projects"][0]
        self.assertEqual(project_result["subtitle_counts"]["matched"], 2)
        self.assertTrue(project_result["eligible"])
        self.assertEqual(project_result["ambiguous_matches"], [])
        self.assertEqual(
            [item["index"] for item in project_result["unmatched_capcut"]],
            [1, 3],
        )

    def test_api_preview_apply_and_single_use_preview(self):
        preview = app.preview_capcut_timing(app.CapCutPreviewRequest(
            projects_dir=str(self.projects_dir),
            srt_dir=str(self.srt_dir),
            allow_overlaps=True,
            extend_project_duration=True,
        ))

        self.assertEqual(preview["summary"]["eligible"], 1)
        result = app.apply_capcut_timing(app.CapCutApplyRequest(
            preview_id=preview["preview_id"],
            selected_numbers=["1"],
        ))
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["updated"]), 1)
        with self.assertRaises(HTTPException):
            app.apply_capcut_timing(app.CapCutApplyRequest(
                preview_id=preview["preview_id"],
                selected_numbers=["1"],
            ))

    def test_text_mismatch_blocks_timing_updates(self):
        self._write_srt(second_text="unmatched subtitle")
        preview = create_preview(
            self.srt_dir,
            self.projects_dir,
            allow_overlaps=True,
            extend_project_duration=True,
        )
        plan = preview.plans["1"]

        self.assertFalse(plan.eligible)
        self.assertEqual(len(plan.mapping), 1)
        self.assertTrue(any("subtitle text did not match uniquely" in item for item in plan.blockers))

    def test_apply_refuses_files_changed_after_preview(self):
        preview = create_preview(
            self.srt_dir,
            self.projects_dir,
            allow_overlaps=True,
            extend_project_duration=True,
        )
        self.draft_path.write_text(self.draft_path.read_text(encoding="utf-8") + " ", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "changed since preview"):
            apply_preview(preview, ["1"])

    def test_preview_blocks_projects_locked_by_capcut(self):
        (self.project_dir / ".locked").touch()

        preview = create_preview(
            self.srt_dir,
            self.projects_dir,
            allow_overlaps=True,
            extend_project_duration=True,
        )

        self.assertFalse(preview.plans["1"].eligible)
        self.assertTrue(any("currently open or locked" in item for item in preview.plans["1"].blockers))

    def test_apply_rechecks_project_lock_after_preview(self):
        preview = create_preview(
            self.srt_dir,
            self.projects_dir,
            allow_overlaps=True,
            extend_project_duration=True,
        )
        (self.project_dir / ".locked").touch()

        result = apply_preview(preview, ["1"])

        self.assertEqual(result["updated"], [])
        self.assertIn("currently open or locked", result["errors"][0]["message"])
        self.assertFalse(self.draft_path.with_name("draft_content.json.bak").exists())


if __name__ == "__main__":
    unittest.main()
