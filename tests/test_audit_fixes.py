import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "dae"))

from PyQt5.QtCore import QMimeData, QUrl
from PyQt5.QtGui import QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import QApplication, QDialog

from gui import customtreeview as tree
from gui.app import MainWindow
from gui.mapDialog import MapTab
from parse.realres import CollisionGeom, GeomNodeTree, Model, SourceModel
from parse.material import TexturePathDict
from util.assetcacher import AssetCacher


class AuditFixesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_map_tab_deselect_and_reload_resets_cells(self):
        tab = MapTab(None)
        self.addCleanup(tab.close)
        layer = SimpleNamespace(grid2world=1.0, cellSz=64, calculatedScale=(1.0, 1.0, 1.0), cellCnt=2, riDataRel={0: object(), 1: object()})
        fake_map = SimpleNamespace(filePath="dummy.bin", riGenLayers=[layer])

        tab.mapLoadFinished(fake_map, [(10, (0, 0), 1, 0, 1), (11, (1, 0), 2, 0, 1)])
        buttons = [tab.gridLayout.itemAt(i).widget() for i in range(tab.gridLayout.count())]
        buttons[0].click()
        buttons[1].click()
        self.assertEqual(tab.cellsToExport, {10, 11})
        self.assertTrue(tab.exportButton.isEnabled())

        # Deselecting one cell while another remains selected must remove it instead of re-adding.
        buttons[0].click()
        self.assertEqual(tab.cellsToExport, {11})
        self.assertTrue(tab.exportButton.isEnabled())

        buttons[1].click()
        self.assertEqual(tab.cellsToExport, set())
        self.assertFalse(tab.exportButton.isEnabled())

        # Reloading another map must clear any prior cell selection.
        buttons[0].click()
        self.assertEqual(tab.cellsToExport, {10})
        tab.mapLoadFinished(fake_map, [(20, (0, 0), 1, 0, 1)])
        self.assertEqual(tab.cellsToExport, set())
        self.assertFalse(tab.exportButton.isEnabled())

    def test_model_get_dmf_handles_unreferenced_vertices(self):
        model = Model("orphaned")
        model.appendVerts([(0, 0, 0), (1, 0, 0), (0, 1, 0), (9, 9, 9)], [(0, 0)] * 4)
        obj = model.newObject("tri")
        obj.appendFace((0, 1, 2))
        data = model.getDMF()
        self.assertTrue(data.startswith(b"DMF\x02"))

    def test_drag_drop_paths_handle_urls_crlf_and_invalid_text(self):
        with tempfile.TemporaryDirectory() as folder:
            a = Path(folder) / "a.grp"
            b = Path(folder) / "b.grp"
            a.touch()
            b.touch()

            url_mime = QMimeData()
            url_mime.setUrls([QUrl.fromLocalFile(str(a)), QUrl.fromLocalFile(str(b))])
            self.assertEqual(tree.CustomTreeView.getEventPaths(None, url_mime), [a.as_posix(), b.as_posix()])

            text_mime = QMimeData()
            text_mime.setText(f"file:///{a.as_posix()}\r\nfile:///{b.as_posix()}\r\n")
            self.assertEqual(tree.CustomTreeView.getEventPaths(None, text_mime), [a.as_posix(), b.as_posix()])

            bad_mime = QMimeData()
            bad_mime.setText("not a real path")
            self.assertIsNone(tree.CustomTreeView.getEventPaths(None, bad_mime))

            single_url = QMimeData()
            single_url.setUrls([QUrl.fromLocalFile(str(a))])
            self.assertEqual(MapTab.getEventPath(None, single_url), a.as_posix())
            self.assertIsNone(MapTab.getEventPath(None, url_mime))
            self.assertIsNone(MapTab.getEventPath(None, bad_mime))

    def test_source_model_sanitizes_invalid_windows_smd_names(self):
        model = Model("f16_cockpit")
        model.appendVerts([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0)] * 3)
        for name in ("Handle:SCREWS:1", "Handle_SCREWS_1"):
            obj = model.newObject(name)
            obj.appendFace((0, 1, 2))

        with tempfile.TemporaryDirectory() as folder:
            smdl = SourceModel("f16_cockpit", model)
            qc_path, _ = smdl.export(folder, "dae_out", exportCollisionModel=False, exportSMD=True)
            qc = Path(qc_path).read_text()
            self.assertIn('$body studio "Handle_SCREWS_1.smd"', qc)
            self.assertIn('$body studio "Handle_SCREWS_1_1.smd"', qc)
            self.assertTrue((Path(qc_path).parent / "Handle_SCREWS_1.smd").is_file())
            self.assertTrue((Path(qc_path).parent / "Handle_SCREWS_1_1.smd").is_file())

    def test_collision_geom_get_skeleton_resolves_base_name(self):
        AssetCacher.clearCache()
        self.addCleanup(AssetCacher.clearCache)
        with tempfile.TemporaryDirectory() as folder:
            dummy_file = Path(folder) / "tank.grp"
            dummy_file.write_bytes(b"0")
            skel = GeomNodeTree(str(dummy_file), name="t_80bvm_skeleton", size=1)
            AssetCacher.cacheAsset(skel)
            col = CollisionGeom(str(dummy_file), name="t_80bvm_collision", size=1)
            self.assertIs(col.getSkeleton(), skel)

    def test_main_window_append_row_routes_root_via_signal(self):
        emitted = []
        tree_model = QStandardItemModel()
        fake_window = SimpleNamespace(
            treeView=SimpleNamespace(treeModel=tree_model),
            rowCreated=SimpleNamespace(emit=emitted.append),
        )
        root_row = [QStandardItem("root")]
        MainWindow._appendRow(fake_window, tree_model, root_row)
        self.assertEqual(emitted, [root_row])
        self.assertEqual(tree_model.rowCount(), 0)

        folder_item = QStandardItem("folder")
        child_row = [QStandardItem("child")]
        MainWindow._appendRow(fake_window, folder_item, child_row)
        self.assertEqual(folder_item.rowCount(), 1)

    def test_export_to_source_fails_when_vtfcmd_produces_no_vtf(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out_model = root / "plane"
            (out_model / "textures").mkdir(parents=True)
            (out_model / "textures" / "albedo.dds").write_bytes(b"DDS ")
            (root / "gameinfo.txt").touch()
            (root / "vtfcmd.exe").touch()

            tex_paths = TexturePathDict("dae_out")
            tex_paths.append("albedo", 0, [], "basetexture")
            stale_vtf = out_model / "source_export/materials/models/dae_out/albedo.vtf"
            stale_vtf.parent.mkdir(parents=True, exist_ok=True)
            stale_vtf.write_bytes(b"stale")

            smdl = SimpleNamespace(
                name="plane",
                export=lambda *a, **k: (str(out_model / "plane.qc"), tex_paths),
                model=SimpleNamespace(materials=[], exportTextures=lambda *a, **k: None),
            )
            asset = SimpleNamespace(name="plane", filePath=str(root / "plane.grp"), getSourceModel=lambda *a, **k: smdl)
            values = {
                tree.SETTINGS_NO_TEX_EXPORT: False,
                tree.SETTINGS_EXPORT_GAMEINFO: False,
                tree.SETTINGS_STUDIOMDL_EXPORT_COLLISION: False,
                tree.SETTINGS_EXPORT_SMD: False,
                tree.SETTINGS_NO_MDL: True,
                tree.SETTINGS_DONT_EXPORT_EXISTING_TEXTURES: False,
                tree.SETTINGS_FORCE_DDS_CONVERSION: False,
                tree.SETTINGS_STUDIOMDL_PATH: "",
                tree.SETTINGS_GAMEINFO_PATH: str(root / "gameinfo.txt"),
                tree.SETTINGS_VTFCMD_PATH: str(root / "vtfcmd.exe"),
            }
            action = SimpleNamespace(
                lod=0,
                exportLODs=False,
                keepBones=None,
                modelPath="dae_out",
                skinArchives=(),
                shouldTerminate=False,
                item=SimpleNamespace(asset=asset),
                setting=lambda k: values[k],
                prepareSourceModel=lambda s: None,
                compileTargets=lambda qc: [],
                setTaskStatus=lambda s: None,
                setTaskProgress=lambda p: None,
                handleTermination=lambda t: False,
                clearTerminable=lambda: None,
                setSubProcess=lambda p: None,
                clearSubProcess=lambda *a: None,
            )
            fake_proc = SimpleNamespace(wait=lambda: 0, returncode=0)
            with patch.object(tree.SETTINGS, "getValue", side_effect=lambda k: values[k]), \
                 patch.object(tree, "cacheHQTextures", return_value=0), \
                 patch.object(tree, "Popen", return_value=fake_proc):
                with self.assertRaisesRegex(RuntimeError, "VTFCmd failed"):
                    tree.ExportToSource.save(action, str(root))
            self.assertFalse(stale_vtf.exists())

    def test_glide_prerun_shows_messagebox_on_cockpit_preflight_error(self):
        with tempfile.TemporaryDirectory() as folder:
            asset = SimpleNamespace(filePath=str(Path(folder) / "j_16.grp"), name="j_16", computeData=lambda: None, geomNodeTree=None)
            action = SimpleNamespace(
                mainWindow=None,
                item=SimpleNamespace(asset=asset),
                previewLoadout=lambda opts: None,
            )
            fake_dialog = SimpleNamespace(
                exec_=lambda: QDialog.Accepted,
                options=lambda: {"cockpit": True, "aircraft": True},
            )
            shown = []
            with patch.object(tree, "findAircraftBlk", return_value={"fm": {}}), \
                 patch.object(tree, "findTankBlk", return_value=None), \
                 patch("util.wtloadout.slotChoices", return_value=[]), \
                 patch.object(tree, "GlideOptionsDialog", return_value=fake_dialog), \
                 patch.object(tree, "MessageBox", side_effect=lambda msg: SimpleNamespace(exec_=lambda: shown.append(msg))):
                result = tree.ExportToGlide.preRun(action)
            self.assertFalse(result)
            self.assertEqual(len(shown), 1)
            self.assertIn("HQ cockpit", shown[0])

    def test_preview_cleanup_gl_deletes_nonzero_textures(self):
        from gui.previewDialog import CustomOpenGL
        deleted = []
        called = []
        gl_widget = SimpleNamespace(
            textures=[0, 7, 12],
            makeCurrent=lambda: called.append("makeCurrent"),
            doneCurrent=lambda: called.append("doneCurrent"),
        )
        with patch("gui.previewDialog.GL.glDeleteTextures", side_effect=lambda ids: deleted.append(list(ids))):
            CustomOpenGL.cleanupGL(gl_widget)
        self.assertEqual(deleted, [[7, 12]])
        self.assertEqual(gl_widget.textures, [])
        self.assertEqual(called, ["makeCurrent", "doneCurrent"])

    def test_log_indentation_is_thread_local_and_clamped(self):
        import threading
        from util import log
        log.subLevel(100)
        self.assertEqual(log.curLevel, 0)
        log.addLevel(2)
        self.assertEqual(log.curLevel, 2)
        worker_levels = []

        def worker():
            worker_levels.append(log.curLevel)
            log.addLevel(1)
            worker_levels.append(log.curLevel)
            log.subLevel(5)
            worker_levels.append(log.curLevel)

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        self.assertEqual(worker_levels, [0, 1, 0])
        self.assertEqual(log.curLevel, 2)
        log.subLevel(2)
        self.assertEqual(log.curLevel, 0)

    def test_settings_load_backs_up_corrupt_json_before_reset(self):
        from util.settings import Settings
        with tempfile.TemporaryDirectory() as folder:
            cfg = Path(folder) / "settings.json"
            cfg.write_text("{invalid json", encoding="utf-8")
            instance = Settings.__new__(Settings)
            instance._Settings__fpath = str(cfg)
            instance.loadSettings()
            self.assertTrue((Path(folder) / "settings.json.bak").is_file())
            self.assertEqual((Path(folder) / "settings.json.bak").read_text(encoding="utf-8"), "{invalid json")
            self.assertIsInstance(instance.getSettings(), dict)

    def test_mtl_uses_clean_texture_filenames(self):
        from parse.material import MaterialData, MaterialTemplateLibrary
        mat = MaterialData()
        mat.setName("wing")
        mat.cls = "dynamic_masked_chrome_bump"
        mat.par = ""
        mat.addTexSlot("t0", "su27_wing_c")
        mat.addTexSlot("t2", "su27_wing_n*?foo")
        mtl = MaterialTemplateLibrary([mat]).getMTL()
        self.assertIn("map_Kd textures/su27_wing_c.dds", mtl)
        self.assertIn("map_bump textures/su27_wing_n.dds", mtl)

    def test_uncache_asset_and_bounds_checks(self):
        from parse.gameres import GameResourcePack
        from parse.material import DDSxTexturePack2
        from parse.mesh import MatVData
        AssetCacher.clearCache()
        self.addCleanup(AssetCacher.clearCache)

        with tempfile.TemporaryDirectory() as folder:
            dummy = Path(folder) / "x.grp"
            dummy.write_bytes(b"0")
            skel = GeomNodeTree(str(dummy), name="test_skel", size=1)
            AssetCacher.cacheAsset(skel)
            self.assertEqual(AssetCacher.getCachedAsset(GeomNodeTree, "test_skel"), [skel])
            AssetCacher.uncacheAsset(skel)
            self.assertEqual(AssetCacher.getCachedAsset(GeomNodeTree, "test_skel"), [])

        fake_mvd = SimpleNamespace(_MatVData__dataComputed=True, _MatVData__gvdata=[object()])
        with self.assertRaises(ValueError):
            MatVData.getVertexData(fake_mvd, 1)

        fake_grp = SimpleNamespace(_GameResourcePack__realResEntries=[object()])
        with self.assertRaises(AssertionError):
            GameResourcePack.getRealResource(fake_grp, 1)

        fake_dxp = SimpleNamespace(
            _DDSxTexturePack2__nameMap=["a", "b"],
            _DDSxTexturePack2__files=[SimpleNamespace(name="a"), SimpleNamespace(name="b")],
            shouldTerminate=False,
        )
        fake_dxp.getDDSxById = lambda idx: DDSxTexturePack2.getDDSxById(fake_dxp, idx)
        self.assertEqual(DDSxTexturePack2.getDDSxByName(fake_dxp, "b").name, "b")
        with self.assertRaises(AssertionError):
            DDSxTexturePack2.getDDSxById(fake_dxp, 2)

    def test_write_addon_reuses_preloaded_labels(self):
        from util.glide import writeAddon
        with tempfile.TemporaryDirectory() as folder, \
             patch("util.glide.generateAircraftLua", return_value="AIRFRAME\n"), \
             patch("util.glide.aircraftGuns", return_value=[]), \
             patch("util.wtweapons.missileLua", return_value="WEAPONS\n") as missile_mock, \
             patch("util.wtloadout.weaponLabels", side_effect=AssertionError("should not reload labels")):
            writeAddon(folder, "wt_test", "Test", "models/wt_glide/test.mdl", None,
                       {"fm": {}}, labels={"weapons/r73": "R-73"})
        self.assertEqual(missile_mock.call_args.kwargs["labels"], {"weapons/r73": "R-73"})

    def test_export_to_source_converts_multiple_vtf_textures_concurrently(self):
        import threading
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out_model = root / "plane"
            (out_model / "textures").mkdir(parents=True)
            (root / "gameinfo.txt").touch()
            (root / "vtfcmd.exe").touch()

            tex_paths = TexturePathDict("dae_out")
            names = [f"tex_{i}" for i in range(6)]
            for tex_name in names:
                (out_model / "textures" / f"{tex_name}.dds").write_bytes(b"DDS ")
                tex_paths.append(tex_name, 0, [], "basetexture")

            smdl = SimpleNamespace(
                name="plane",
                export=lambda *a, **k: (str(out_model / "plane.qc"), tex_paths),
                model=SimpleNamespace(materials=[], exportTextures=lambda *a, **k: None),
            )
            asset = SimpleNamespace(name="plane", filePath=str(root / "plane.grp"), getSourceModel=lambda *a, **k: smdl)
            values = {
                tree.SETTINGS_NO_TEX_EXPORT: False,
                tree.SETTINGS_EXPORT_GAMEINFO: False,
                tree.SETTINGS_STUDIOMDL_EXPORT_COLLISION: False,
                tree.SETTINGS_EXPORT_SMD: False,
                tree.SETTINGS_NO_MDL: True,
                tree.SETTINGS_DONT_EXPORT_EXISTING_TEXTURES: False,
                tree.SETTINGS_FORCE_DDS_CONVERSION: False,
                tree.SETTINGS_STUDIOMDL_PATH: "",
                tree.SETTINGS_GAMEINFO_PATH: str(root / "gameinfo.txt"),
                tree.SETTINGS_VTFCMD_PATH: str(root / "vtfcmd.exe"),
            }
            lock = threading.Lock()
            active = 0
            peak = 0
            tracked_procs = {}
            progress_updates = []
            both_started = threading.Barrier(2, timeout=2.0)

            def fake_popen(cmd):
                nonlocal active, peak
                dds = Path(cmd[cmd.index("-file") + 1])
                out_dir = Path(cmd[cmd.index("-output") + 1])
                with lock:
                    active += 1
                    peak = max(peak, active)
                try:
                    both_started.wait()
                except threading.BrokenBarrierError:
                    pass
                (out_dir / f"{dds.stem}.vtf").write_bytes(b"VTF")
                with lock:
                    active -= 1
                return SimpleNamespace(wait=lambda: 0, returncode=0)

            action = SimpleNamespace(
                lod=0,
                exportLODs=False,
                keepBones=None,
                modelPath="dae_out",
                skinArchives=(),
                shouldTerminate=False,
                item=SimpleNamespace(asset=asset),
                setting=lambda k: values[k],
                prepareSourceModel=lambda s: None,
                compileTargets=lambda qc: [],
                setTaskStatus=lambda s: None,
                setTaskProgress=lambda p: progress_updates.append(p),
                handleTermination=lambda t: False,
                clearTerminable=lambda: None,
                setSubProcess=lambda p: tracked_procs.__setitem__(id(p), p),
                clearSubProcess=lambda p=None: tracked_procs.pop(id(p), None) if p else tracked_procs.clear(),
            )
            with patch.object(tree.SETTINGS, "getValue", side_effect=lambda k: values[k]), \
                 patch.object(tree, "cacheHQTextures", return_value=0), \
                 patch.object(tree, "Popen", side_effect=fake_popen):
                tree.ExportToSource.save(action, str(root))

            self.assertGreaterEqual(peak, 2)
            self.assertEqual(tracked_procs, {})
            self.assertEqual(progress_updates[-1], 1.0)
            self.assertEqual(len(progress_updates), len(names) + 5)
            for tex_name in names:
                self.assertTrue((out_model / "source_export/materials/models/dae_out" / f"{tex_name}.vtf").is_file())

    def test_main_window_subprocess_tracking_handles_concurrent_procs(self):
        import threading
        killed = []
        procs = [SimpleNamespace(kill=lambda i=i: killed.append(i)) for i in range(3)]
        fake_window = SimpleNamespace(
            activeTerminable=None,
            activeSubProcess=None,
            _subProcesses={},
            _subProcessLock=threading.Lock(),
            shouldTerminate=False,
            threadPool=SimpleNamespace(waitForDone=lambda: None),
            clearTerminable=lambda: None,
            clearSubProcess=lambda: MainWindow.clearSubProcess(fake_window),
            setRequestedDialog=lambda d: None,
        )
        for proc in procs:
            MainWindow.setSubProcess(fake_window, proc)
        MainWindow.clearSubProcess(fake_window, procs[1])
        self.assertEqual(set(fake_window._subProcesses), {id(procs[0]), id(procs[2])})
        MainWindow.terminateThreads(fake_window)
        self.assertEqual(set(killed), {0, 2})
        self.assertEqual(fake_window._subProcesses, {})

    def test_cockpit_export_converts_multiple_vtf_textures_concurrently(self):
        import threading
        from contextlib import ExitStack
        from util.wtcockpit import exportCockpit
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            pack = root / "j_16.grp"
            tools = [root / n for n in ("studiomdl.exe", "gameinfo.txt", "vtfcmd.exe")]
            for file in tools:
                file.touch()
            out, addon = root / "source", root / "addon"
            qcdir = out / "j_16_cockpit"
            qcdir.mkdir(parents=True)
            qc = qcdir / "j_16_cockpit.qc"
            qc.write_text("$opaque\n")
            target = qcdir / "j_16_cockpit_0.qc"
            target.touch()
            materials = qcdir / "source_export/materials"
            materials.mkdir(parents=True)
            (qcdir / "textures").mkdir()
            names = [f"tex_{i}" for i in range(4)]
            for tex_name in names:
                (qcdir / "textures" / f"{tex_name}.dds").touch()
            model = SimpleNamespace(materials=[], skeleton=object(), exportTextures=lambda *a, **k: None)
            dyn = SimpleNamespace(name="j_16_cockpit", getModel=lambda _: model)
            stack.enter_context(patch("util.wtcockpit.cockpitPack", return_value=pack))
            stack.enter_context(patch("parse.realres.DynModel", SimpleNamespace))
            stack.enter_context(patch("parse.gameres.GameResDesc"))
            archive = stack.enter_context(patch("parse.gameres.GameResourcePack"))
            archive.return_value.getPackedFiles.return_value = [dyn]
            stack.enter_context(patch("util.assetcacher.AssetCacher.cacheAsset"))
            stack.enter_context(patch("util.assetcacher.AssetCacher.appendGameResDesc"))
            stack.enter_context(patch("util.wtcockpit.prepareInterior", return_value=(set(), {"surfaces": {}})))
            stack.enter_context(patch("util.a2d.A2D.fromPack"))
            stack.enter_context(patch("util.wtcockpit.stickPoses", return_value={}))
            vrom = stack.enter_context(patch("util.vromfs.VROMFS"))
            vrom.return_value.readBlk.return_value = {"cockpit": {"headPos": [7.8, 1, 0]}}
            source = stack.enter_context(patch("parse.realres.SourceModel"))
            source.return_value.export.return_value = (str(qc), SimpleNamespace(
                getDict=lambda: {n: SimpleNamespace(texPath=n) for n in names}))
            stack.enter_context(patch("util.wtcockpit.splitCockpitQC", return_value=[target]))
            stack.enter_context(patch("util.wtcockpit.exportDisplayArtwork"))
            stack.enter_context(patch("util.wtcockpit.cockpitLua", return_value="COCKPIT"))

            lock = threading.Lock()
            active = 0
            peak = 0
            barrier = threading.Barrier(2, timeout=2.0)

            def run(command):
                nonlocal active, peak
                if command[0] == str(tools[2]):
                    dds = Path(command[command.index("-file") + 1])
                    out_dir = Path(command[command.index("-output") + 1])
                    with lock:
                        active += 1
                        peak = max(peak, active)
                    try:
                        barrier.wait()
                    except threading.BrokenBarrierError:
                        pass
                    (out_dir / f"{dds.stem}.vtf").touch()
                    with lock:
                        active -= 1
                    return
                stage = Path(command[command.index("-game") + 1])
                dest = stage / "models/wt_glide/cockpits/j_16"
                dest.mkdir(parents=True)
                for suffix in (".mdl", ".vvd", ".dx90.vtx"):
                    (dest / (target.stem + suffix)).touch()

            self.assertEqual(exportCockpit(root, "j_16", out, addon, *tools, run), "COCKPIT")
            self.assertGreaterEqual(peak, 2)


if __name__ == "__main__":
    unittest.main()
