import sys
from os import path, system, mkdir, makedirs, remove, replace, listdir, rmdir

sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))

from util.classproperty import classproperty

import shutil
import util.log as log
from PyQt5.QtWidgets import QAbstractItemView, QApplication, QTreeView, QLineEdit, QHeaderView, QMenu, QAction, QStyledItemDelegate, QFileDialog, QMainWindow, QDialog
from PyQt5.QtCore import QMimeData, Qt, QSortFilterProxyModel, QPoint, QFileInfo, QSize
from PyQt5.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QStandardItemModel, QStandardItem, QIcon, QPaintEvent, QPainter, QPalette
from util.misc import formatBytes, getResPath, openFile, ROOT_FOLDER, LIB_FOLDER
from util.terminable import Exportable, Packed, Pack, Terminable
from util.enums import *
from functools import partial
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event
from parse.material import DDSx, DDSxTexturePack2
from parse.realres import RendInst, DynModel, ModelContainer, GeomNodeTree
from gui.glideOptionsDialog import GlideOptionsDialog
from util.glide import GLIDE_KEEP_BONES, TRACK_R_SUFFIX, cacheHQTextures, compileSmokeModels, defaultOptions, findGameRoot, findTankBlk, glideCollisionNodes, hiddenNodes, prepareTankSmoke, splitTrackMaterials, tankMassCenter, writeAddon
from util.glide import aircraftCollisionNodes, aircraftHiddenNodes, aircraftKeepBones, controlSurfaces, findAircraftBlk, findAircraftCollision, gearSequences, isAircraft
from util.a2d import A2D
import re
from parse.gameres import GameResourcePack
from traceback import format_exc
from gui.progressDialog import MessageBox
from util.settings import SETTINGS
from util.i18n import tr
from subprocess import Popen
from glob import glob


FOLDER_ICO_PATH = getResPath("folder.bmp")
VTFCMD_PATH = path.join(LIB_FOLDER, "VTFcmd.exe")

class SafeStandardItem(QStandardItem):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
	
	def setParentItem(self, item):
		item.mainWindow.clearItems.append(lambda: self.clearData())

		self.setData(item, Qt.UserRole)

class SimpleItem:
	def __init__(self, mainWindow:QMainWindow, finfo:QFileInfo, type:str, icon:QIcon, name:str = None):
		self.mainWindow = mainWindow

		self.finfo = finfo

		mainItem = SafeStandardItem(name if name is not None else finfo.fileName())
		mainItem.setParentItem(self) # WARNING: if the data is not cleared manually, this will lead to memory leaks (fuck qt for that)
		mainItem.setIcon(icon)

		self.mainItem = mainItem

		fileType = SafeStandardItem(type)
		fileType.setParentItem(self)

		self.fileType = fileType

	def populateMenu(self, menu:QMenu):
		if self.hasParent():
			menu.addAction(OpenParentFileLocation(menu, self))
		else:
			menu.addAction(OpenFileLocation(menu, self))
		
		if self.finfo is not None:
			menu.addAction(CopyPathToClipboard(menu, self))
		
		# if len(menu.children()) > 0:
		# 	menu.addSeparator()
		
		if isinstance(self, AssetItem):
			asset = self.asset

			menu.addAction(CopyNameToClipboard(menu, self))
		
			menu.addSeparator()

			if isinstance(asset, Packed) and self.hasParent():
				menu.addAction(Extract(menu, self))

			if isinstance(asset, DDSx):
				menu.addAction(ExportToDDS(menu, self))
			elif isinstance(asset, ModelContainer):
				level = log.curLevel

				try:

					if isinstance(asset, GeomNodeTree):
						menu.addAction(ExportSkeletonToDMF(menu, self, 0))
					else:
						menu.addAction(ExportToDMF(menu, self, 0))
					
					if isinstance(asset, RendInst):
						menu.addAction(PreviewModel(menu, self, 0))
						menu.addAction(ExportToSource(menu, self, 0))

						if isinstance(asset, DynModel):
							menu.addAction(ExportToGlide(menu, self, 0))

						menu.addAction(ExportToOBJ(menu, self, 0))

						asset.computeData()

						if asset.lodCount > 1:
							submenu = menu.addMenu(tr("Export LOD..."))

							for i in range(asset.lodCount):
								submenu.addAction(PreviewModel(menu, self, i))

							submenu.addSeparator()

							for i in range(asset.lodCount):
								submenu.addAction(ExportToDMF(menu, self, i))

							submenu.addSeparator()
							
							for i in range(asset.lodCount):
								submenu.addAction(ExportToOBJ(menu, self, i))

							submenu.addSeparator()

							submenu.addAction(ExportLODsToDMF(menu, self))
							submenu.addAction(ExportLODsToOBJ(menu, self))
							submenu.addAction(ExportLODsToSource(menu, self))
				except Exception as e:
					print(format_exc())

					log.subLevel(log.curLevel - level)

					MessageBox(tr("Failed to compute preliminary data. Check the console for details.")).exec_()
			elif isinstance(asset, Pack):
				menu.addAction(ExtractAll(menu, self))

				if isinstance(asset, DDSxTexturePack2):
					menu.addAction(ExportAllToDDS(menu, self))
				elif isinstance(asset, GameResourcePack):
					menu.addAction(ExportAllToDMF(menu, self))
					menu.addAction(ExportAllToOBJ(menu, self))
					# menu.addAction(ExportAllLODsToOBJ(menu, self))
	
	def autoExpand(self):
		if SETTINGS.getValue(SETTINGS_EXPAND_ALL):
			self.expand()

	def expand(self):
		treeView:CustomTreeView = self.mainWindow.treeView
		treeView.expand(self.mainItem.index())

	def getRow(self):
		return (self.mainItem, self.fileType, None)

	def hasParent(self):
		return False

	def getParentItem(self):
		return self

class AssetItem(SimpleItem):
	def __init__(self, mainWindow:QMainWindow, finfo:QFileInfo, icon:QIcon, asset:Exportable, parentPackage:SimpleItem = None):
		super().__init__(mainWindow,
		   finfo, 
		   asset.niceName, 
		   icon, 
		   finfo.fileName() if parentPackage is None else asset.name)

		self.parentPackage = parentPackage

		fileSize = SafeStandardItem(str(asset.size))
		fileSize.setParentItem(self)
		self.fileSize = fileSize
		
		self.asset = asset
	

	def expand(self):
		treeView:CustomTreeView = self.mainWindow.treeView
		treeView.expandRecursively(self.mainItem.index())

	def hasParent(self):
		return self.parentPackage is not None

	def getParentItem(self):
		if self.parentPackage is None:
			return self
		else:
			return self.parentPackage.getParentItem()
	
	def getRow(self):
		return (self.mainItem, self.fileType, self.fileSize)

class FolderItem(SimpleItem):
	__ICON = None
	__TYPE = tr("Folder")

	def __init__(self, mainWindow:QMainWindow, finfo:QFileInfo):
		if not FolderItem.__ICON:
			FolderItem.__ICON = QIcon(FOLDER_ICO_PATH)
		
		super().__init__(mainWindow,
		   finfo, 
		   FolderItem.__TYPE, 
		   FolderItem.__ICON)

class CustomAction(QAction):
	def __init__(self, parent, item:SimpleItem):
		super().__init__(parent)

		self.__item = item

		self.setText(self.actionText)

		self.triggered.connect(self.run)
	
	@property
	def item(self):
		return self.__item

	def run(self):
		raise NotImplementedError()
	
	@property
	def mainWindow(self):
		return self.item.mainWindow

	@property
	def actionText(self) -> str:
		raise NotImplementedError()

class ThreadedAction(CustomAction):
	def __init__(self, parent, item:SimpleItem):
		super().__init__(parent, item)
		
		self.triggered.disconnect()

		self.triggered.connect(self.__run__)

		self.__error = False
		self.__cancel = False
	
	@property
	def taskTitle(self) -> str:
		raise NotImplementedError()
	
	@classproperty
	def dialogType(self) -> int:
		raise NotImplementedError()

	def setTerminable(self, ter:Terminable):
		self.item.mainWindow.setTerminable(ter)
	
	def setSubProcess(self, proc):
		self.item.mainWindow.setSubProcess(proc)
	
	def clearTerminable(self):
		self.item.mainWindow.clearTerminable()
	
	def clearSubProcess(self, proc = None):
		if proc is None:
			self.item.mainWindow.clearSubProcess()
		else:
			self.item.mainWindow.clearSubProcess(proc)
	
	def handleTermination(self, ter:Terminable):
		if self.shouldTerminate:
			return True
		else:
			self.setTerminable(ter)

			return False

	@property
	def shouldTerminate(self) -> bool:
		return self.item.mainWindow.shouldTerminate

	def setTaskStatus(self, text:str):
		self.mainWindow.setTaskStatus(text)
	
	@property
	def taskStatus(self) -> str:
		return self.mainWindow.getTaskStatus()

	def setTaskProgress(self, progress:float):
		self.mainWindow.setTaskProgress(progress * 100)

	def preRun(self) -> bool:
		return True
	
	def setErrored(self):
		self.__error = True
	
	def __run__(self):
		if not self.preRun():
			return

		self.mainWindow.setRequestedDialog(self.dialogType)
		self.mainWindow.setTaskTitle(self.taskTitle)
		self.setTaskStatus(self.taskTitle)

		self.mainWindow.threadPool.start(partial(self.__threadedRun__))


	def cancel(self):
		self.__cancel = True
	
	@property
	def cancelled(self):
		return self.__cancel
	
	def __threadedRun__(self):
		level = log.curLevel

		try:
			self.run()
		except Exception as e:
			self.setErrored()

			print(format_exc())

			log.subLevel(log.curLevel - level)
		
		if self.__error:
			self.mainWindow.setRequestedDialog(DIALOG_ERROR)
		
		self.mainWindow.setRequestedDialog(DIALOG_NONE)

class OpenFileLocation(CustomAction):
	def run(self):
		system('explorer.exe /select,"' + path.normpath(self.item.finfo.absoluteFilePath()) + '"')
	
	@property
	def actionText(self) -> str:
		return tr("Open file location")

class OpenParentFileLocation(OpenFileLocation):
	@property
	def actionText(self) -> str:
		return tr("Open parent location")
	
	
	def run(self):
		parentItem = self.item.getParentItem()

		system('explorer.exe /select,"' + path.normpath(parentItem.finfo.absoluteFilePath()) + '"')

class CopyPathToClipboard(CustomAction):
	def run(self):
		QApplication.clipboard().setText(self.item.finfo.absoluteFilePath())
	
	@property
	def actionText(self) -> str:
		return tr("Copy path to clipboard")

class CopyNameToClipboard(CustomAction):
	item:AssetItem

	def run(self):
		QApplication.clipboard().setText(self.item.asset.name)
	
	@property
	def actionText(self) -> str:
		return tr("Copy name to clipboard")



class SaveAction(ThreadedAction):
	item:AssetItem

	def preRun(self):
		if SETTINGS.getValue(SETTINGS_OUTPUT_FOLDER):
			self.output = ROOT_FOLDER

			self.makeOutputFolder(True, "output")
		else:
			dialog = openFile(title = tr("Save to"), fileMode = QFileDialog.DirectoryOnly)

			if dialog == None:
				return
			
			self.output = dialog.selectedFiles()[0]

		return self.output is not None

	def run(self):
		self.save(self.output)
	
	@classproperty
	def dialogType(self) -> int:
		return DIALOG_PROGRESS
	
	def save(self, output:str):
		raise NotImplementedError()
	
	def makeOutputFolder(self, shouldMakeFolder:bool, folderName:str):
		if not shouldMakeFolder:
			return self.output
		
		self.output = path.join(self.output, folderName)

		if not path.exists(self.output):
			mkdir(self.output)
		
		return self.output

class AssetSaveAction(SaveAction):
	def saveSingle(self, output:str, asset):
		if self.handleTermination(asset):
			return True
		
		level = log.curLevel

		log.log(self.taskStatus)
		log.addLevel()

		try:
			self.saveAsset(output, asset)

			log.subLevel()
		except Exception as e:
			print(format_exc())

			self.setErrored()

			log.subLevel(log.curLevel - level)

		return False
	
	def saveAsset(self, output:str, asset):
		raise NotImplementedError()
	
	def save(self, output:str):
		asset:Packed = self.item.asset
		
		self.saveSingle(output, asset)

		self.setTaskProgress(1)

class PackedSave(AssetSaveAction):
	def save(self, output:str):
		asset:Pack = self.item.asset

		output = self.makePackedOutputFolder(asset.name)
		
		self.setTerminable(asset)

		packedFiles = asset.getPackedFiles()

		if self.hasFilter:
			fileCnt = 0

			for v in packedFiles:
				if self.filter(v):
					fileCnt += 1
		else:
			fileCnt = len(packedFiles)

		k = 0

		for v in packedFiles:
			if self.hasFilter and not self.filter(v):
				continue

			self.setTaskStatus(f"{self.getProgressText(v)} ({k + 1}/{fileCnt})")

			if self.saveSingle(output, v):
				break
				
			self.setTaskProgress((k + 1) / fileCnt)

			k += 1
		
		self.clearTerminable()
	
	@classproperty
	def hasFilter(cls):
		return False

	def filter(self, asset):
		return True
	
	def getProgressText(self, asset:Packed) -> str:
		raise NotImplementedError()
	
	def makePackedOutputFolder(self, name:str):
		return self.makeOutputFolder(SETTINGS.getValue(SETTINGS_EXPORT_FOLDER), name)


class Extract(AssetSaveAction):
	@property
	def actionText(self) -> str:
		return tr("Extract")
	
	@property
	def taskTitle(self) -> str:
		return tr("Extracting {file}", file = f"{self.item.asset.name}.{self.item.asset.fileExtension}")

	def saveAsset(self, output:str, asset:Packed):
		asset.save(output)

class ExtractAll(Extract, PackedSave):
	@property
	def actionText(self) -> str:
		return tr("Extract all")
	
	@property
	def taskTitle(self) -> str:
		return tr("Extracting files from {file}", file = f"{self.item.asset.name}.{self.item.asset.fileExtension}")
	
	def makePackedOutputFolder(self, name:str):
		return self.makeOutputFolder(SETTINGS.getValue(SETTINGS_EXTRACT_FOLDER), name)

	def getProgressText(self, asset:Packed):
		return tr("Extracting {file}", file = f"{asset.name}.{asset.fileExtension}")


class ExportToDDS(Extract):
	@property
	def actionText(self) -> str:
		return tr("Export to DDS")
	
	@property
	def taskTitle(self) -> str:
		return tr("Exporting to {file}", file = f"{self.item.asset.name}.dds")

	def saveAsset(self, output:str, asset:DDSx):
		asset.exportDDS(output)

class ExportAllToDDS(ExportToDDS, PackedSave):
	@property
	def actionText(self) -> str:
		return tr("Export all to DDS")
	
	@property
	def taskTitle(self) -> str:
		return tr("Exporting files from {file} to DDS", file = f"{self.item.asset.name}.{self.item.asset.fileExtension}")

	def getProgressText(self, asset:Packed):
		return tr("Extracting {file}", file = f"{asset.name}.dds")
	

class PreviewModel(CustomAction):
	def __init__(self, parent, item: SimpleItem, lod:int):
		self.lod = lod

		super().__init__(parent, item)
	
	item:AssetItem

	@property
	def actionText(self) -> str:
		return tr("Preview LOD {lod}", lod = self.lod)
	
	@property
	def taskTitle(self) -> str:
		return tr("Previewing {file}", file = self.item.asset.getExportName(self.lod))

	def run(self):
		from gui.previewDialog import PreviewDialog, buildMeshParts
		from PyQt5.QtWidgets import QApplication

		asset:RendInst = self.item.asset
		level = log.curLevel

		# shortcut: builds on the UI thread (UI freezes on huge models), move to ThreadedAction if that hurts
		QApplication.setOverrideCursor(Qt.WaitCursor)

		try:
			parts = buildMeshParts(asset.getModel(self.lod))
		except Exception:
			print(format_exc())
			log.subLevel(log.curLevel - level)
			parts = None
		finally:
			QApplication.restoreOverrideCursor()

		if parts is None:
			MessageBox(tr("Failed to compute preliminary data. Check the console for details.")).exec_()
		else:
			PreviewDialog(self.mainWindow, self.taskTitle, parts).show()



def _resolveVtfFormat(action) -> str:
	fmt = getattr(action, "vtfFormat", None)
	if fmt not in (VTF_FORMAT_DXT5, VTF_FORMAT_RGBA8888):
		try:
			fmt = SETTINGS.getValue(SETTINGS_VTF_FORMAT)
		except KeyError:
			fmt = VTF_FORMAT_DXT5
	return fmt if fmt in (VTF_FORMAT_DXT5, VTF_FORMAT_RGBA8888) else VTF_FORMAT_DXT5


class ExportToSource(SaveAction):
	def __init__(self, parent, item: SimpleItem, lod:int):
		self.lod = lod

		super().__init__(parent, item)
	
	@property
	def actionText(self) -> str:
		return tr("Export LOD {lod} to Source engine", lod = self.lod)
	
	@property
	def taskTitle(self) -> str:
		return tr("Exporting LOD {lod} to {file}", lod = self.lod, file = f"{self.item.asset.name}.mdl")

	def preRun(self):
		from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QDialogButtonBox
		from gui.skinImportWidget import SkinImportWidget
		dialog = QDialog(self.mainWindow)
		dialog.setWindowTitle(tr("MDL skins"))
		layout = QVBoxLayout(dialog)
		fmtRow = QHBoxLayout()
		fmtRow.addWidget(QLabel(tr("VTF texture format")))
		fmtBox = QComboBox()
		fmtBox.addItem("DXT5", VTF_FORMAT_DXT5)
		fmtBox.addItem("RGBA8888", VTF_FORMAT_RGBA8888)
		fmtIdx = fmtBox.findData(_resolveVtfFormat(self))
		fmtBox.setCurrentIndex(fmtIdx if fmtIdx >= 0 else 0)
		fmtRow.addWidget(fmtBox)
		layout.addLayout(fmtRow)
		skins = SkinImportWidget(dialog, self.item.asset.name, findGameRoot(self.item.asset.filePath))
		layout.addWidget(skins)
		buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
		buttons.accepted.connect(dialog.accept)
		buttons.rejected.connect(dialog.reject)
		layout.addWidget(buttons)
		if dialog.exec_() != QDialog.Accepted:
			return False
		self.vtfFormat = fmtBox.currentData()
		SETTINGS.setValue(SETTINGS_VTF_FORMAT, self.vtfFormat)
		self.skinArchives = skins.paths()
		return super().preRun()

	modelPath = "dae_out"
	skinArchives = ()
	vtfFormat = None
	keepBones = None
	forcedSettings = {}

	def setting(self, key):
		return self.forcedSettings.get(key, SETTINGS.getValue(key))

	def prepareSourceModel(self, smdl):
		pass

	def compileTargets(self, qc):
		return [(qc, self.item.asset.name)]

	def save(self, output:str):
		modelPath = self.modelPath
		asset:RendInst = self.item.asset
		exportTex = not self.setting(SETTINGS_NO_TEX_EXPORT)
		exportToGame = self.setting(SETTINGS_EXPORT_GAMEINFO)
		exportCollisionModel = self.setting(SETTINGS_STUDIOMDL_EXPORT_COLLISION)
		exportSMDs = self.setting(SETTINGS_EXPORT_SMD)
		dontCompile = self.setting(SETTINGS_NO_MDL)
		dontReplaceTex = SETTINGS.getValue(SETTINGS_DONT_EXPORT_EXISTING_TEXTURES)
		forceConvert = SETTINGS.getValue(SETTINGS_FORCE_DDS_CONVERSION)
		vtfFormat = _resolveVtfFormat(self)

		compiler = SETTINGS.getValue(SETTINGS_STUDIOMDL_PATH)
		gameInfo = SETTINGS.getValue(SETTINGS_GAMEINFO_PATH)
		vtfCmd = SETTINGS.getValue(SETTINGS_VTFCMD_PATH) or VTFCMD_PATH
		requiredPaths = []
		if exportSMDs and not dontCompile:
			requiredPaths.append(("StudioMDL", compiler))
		if (exportSMDs and not dontCompile) or exportToGame:
			requiredPaths.append(("gameinfo.txt", gameInfo))
		if exportTex:
			requiredPaths.append(("VTFCmd", vtfCmd))
		for label, filePath in requiredPaths:
			if not path.isfile(filePath):
				raise ValueError(tr("Set a valid {tool} file in Settings before exporting. Current path: {path}", tool = label, path = repr(filePath)))

		if exportTex:
			stepCnt = 5
		else:
			stepCnt = 3
		
		self.setTaskStatus(tr("Generating model data"))

		if self.handleTermination(asset):
			return
		
		smdl = asset.getSourceModel(self.lod, exportLODs = self.exportLODs, keepBones = self.keepBones)
		self.smdl = smdl
		self.prepareSourceModel(smdl)
		self.setTaskProgress(1/stepCnt)
		
		if self.handleTermination(smdl):
			return

		if exportTex:
			self.setTaskStatus(tr("Looking for HQ textures"))
			log.log(f"Cached {cacheHQTextures(findGameRoot(asset.filePath), getattr(asset, 'textures', None))} HQ textures")
		
		self.setTaskStatus(tr("Exporting model data to QC, SMD and VMT"))
		qc, texturePaths = smdl.export(output, modelPath, exportCollisionModel, exportSMDs)
		if self.skinArchives:
			if not exportTex or not exportSMDs:
				raise ValueError("Skin import requires SMD and texture export")
			from util.wtskins import importSkins
			report = importSkins(qc, smdl.model.materials, texturePaths, self.skinArchives, vtfCmd, asset.name, findGameRoot(asset.filePath), vtfFormat = vtfFormat)
			for skin in report:
				log.log(f"Skin {skin['skin']}: {skin['name']}; unused replacements: {skin['unused']}")
		compileTargets = self.compileTargets(qc) if exportSMDs else []
		self.setTaskProgress(2/stepCnt)
		self.clearTerminable()
	
		if self.shouldTerminate:
			return
		
		gamePath = path.dirname(gameInfo)

		output = path.join(output, smdl.name)
		sourceExport = path.join(output, "source_export")

		makedirs(sourceExport, exist_ok = True)

		if exportSMDs and not dontCompile:
			if self.shouldTerminate:
				return
			
			self.setTaskStatus(tr("Compiling"))

			for compileQC, modelName in compileTargets:
				if self.shouldTerminate:
					return
				pipes = Popen([compiler, "-nop4", "-verbose", "-game", gamePath, str(compileQC)])
				self.setSubProcess(pipes)
				if pipes.wait() != 0:
					raise Exception(f"Compile failed ({modelName}): return code {pipes.returncode}")
				self.clearSubProcess()

			if not exportToGame:
				if self.shouldTerminate:
					return
				
				modelOutPath = path.join(sourceExport, f"models/{modelPath}")

				makedirs(modelOutPath, exist_ok = True)
				
				files = [f for _, modelName in compileTargets for f in glob(path.join(gamePath, f"models/{modelPath}/{modelName}.*"))]

				for f in files:
					if self.shouldTerminate:
						return
					
					log.log(f"Moving {f} to {modelOutPath}")
					shutil.move(f, path.join(modelOutPath, path.basename(f)))
			
		self.setTaskProgress(3/stepCnt)

		if exportTex and texturePaths is not None:
			self.setTaskStatus(tr("Exporting textures"))
			log.addLevel()
			try:
				mdl = smdl.model

				if self.handleTermination(mdl):
					return

				mdl.exportTextures(output, texturePaths = texturePaths, forceConvert = forceConvert)
				self.clearTerminable()
			finally:
				log.subLevel()

			if self.shouldTerminate:
				return

			self.setTaskProgress(4/stepCnt)
			self.setTaskStatus(tr("Converting textures to VTF"))
			log.addLevel()
			try:
				materialsPath = path.join(sourceExport, "materials")

				texDict = texturePaths.getDict()
				totalTex = len(texDict)
				jobs = []

				for k, texName in enumerate(texDict.keys()):
					if self.shouldTerminate:
						return

					texFile = path.join(output, f"textures/{texName}.dds")

					if not path.exists(texFile):
						log.log(f"Skipping missing texture {texName}")

						continue

					tex = texturePaths.get(texName)

					texOutPath = path.normpath(path.join(materialsPath, tex.texPath))
					vtfFile = path.join(texOutPath, f"{texName}.vtf")

					if dontReplaceTex and path.exists(vtfFile):
						log.log(f"Skipping already exported texture {texName}")

						continue

					makedirs(texOutPath, exist_ok = True)
					if path.exists(vtfFile):
						remove(vtfFile)

					jobs.append((k, texName, texFile, texOutPath, vtfFile, tex.texType))

				if jobs:
					stop = Event()

					def convertOne(job):
						_, texName, texFile, texOutPath, vtfFile, texType = job
						if stop.is_set() or self.shouldTerminate:
							return False

						cmd = [
							vtfCmd,
							"-file",
							path.normpath(texFile),
							"-output",
							texOutPath,
							"-format",
							vtfFormat,
							"-alphaformat",
							vtfFormat,
						]
						if texType == TEXTURE_NORMAL:
							cmd += ["-flag", "NORMAL"]

						pipes = Popen(cmd)

						self.setSubProcess(pipes)
						try:
							ret = pipes.wait()
						finally:
							try:
								self.clearSubProcess(pipes)
							except TypeError:
								self.clearSubProcess()

						if stop.is_set() or self.shouldTerminate:
							return False
						if ret != 0 or not path.isfile(vtfFile):
							stop.set()
							raise RuntimeError(f"VTFCmd failed for {texName} (return code {ret}): {vtfFile}")
						return True

					if len(jobs) == 1:
						if not convertOne(jobs[0]) or self.shouldTerminate:
							return
						self.setTaskProgress((4 + (jobs[0][0] + 1) / totalTex) / stepCnt)
					else:
						with ThreadPoolExecutor(max_workers = min(4, len(jobs))) as pool:
							futures = [pool.submit(convertOne, job) for job in jobs]
							completed = 0
							try:
								for future in as_completed(futures):
									if not future.result() or self.shouldTerminate:
										stop.set()
										return
									completed += 1
									self.setTaskProgress((4 + completed / len(jobs)) / stepCnt)
							except Exception:
								stop.set()
								raise

				if exportToGame and path.exists(materialsPath):
					log.log("Moving materials directory...")

					shutil.copytree(materialsPath, path.join(gamePath, "materials"), dirs_exist_ok = True)
					shutil.rmtree(materialsPath)


				if len(listdir(sourceExport)) == 0:
					rmdir(sourceExport)
			finally:
				log.subLevel()
			self.setTaskProgress(5/stepCnt)

	@classproperty
	def exportLODs(cls):
		return False

class ExportToGlide(ExportToSource):
	def previewLoadout(self, options):
		from copy import deepcopy
		from gui.previewDialog import PreviewDialog, buildMeshParts
		from PyQt5.QtWidgets import QApplication
		from util.wtloadout import apply, resolve, hardpointMarkers
		from util.vromfs import VROMFS
		QApplication.setOverrideCursor(Qt.WaitCursor)
		try:
			# Match the existing preview path; clone before merging to keep cached geometry intact.
			model = deepcopy(self.item.asset.getModel(self.lod))
			selected = []
			if options.get("loadout"):
				root = findGameRoot(self.item.asset.filePath)
				selected = resolve(self.blk, options["loadout"], VROMFS(path.join(root, 'aces.vromfs.bin')))
				apply(model, self.blk, options["loadout"], root, set(), previewOnly=True)
			else:
				model.removeObjects(aircraftHiddenNodes([o.name for o in model], self.blk))
			markers = hardpointMarkers(self.blk or {}, model.skeleton, selected)
			parts = buildMeshParts(model)
		except Exception as error:
			print(format_exc())
			MessageBox(str(error)).exec_()
			return
		finally:
			QApplication.restoreOverrideCursor()
		PreviewDialog(self.mainWindow, self.item.asset.name, parts, markers).exec_()

	modelPath = "wt_glide"
	keepBones = GLIDE_KEEP_BONES
	forcedSettings = {SETTINGS_EXPORT_GAMEINFO: False, SETTINGS_STUDIOMDL_EXPORT_COLLISION: True, SETTINGS_EXPORT_SMD: True, SETTINGS_NO_MDL: False, SETTINGS_NO_TEX_EXPORT: False}

	@property
	def actionText(self) -> str:
		return tr("Export to Gmod Glide addon")

	@property
	def taskTitle(self) -> str:
		return tr("Exporting {file} to Gmod Glide", file = self.item.asset.name)

	def preRun(self):
		asset:DynModel = self.item.asset
		try:
			self.blk = findAircraftBlk(asset.filePath, asset.name) or findTankBlk(asset.filePath, asset.name)
			self.a2d = self.surfaces = None
			asset.computeData()

			if self.blk is None and asset.geomNodeTree is not None and aircraftKeepBones(asset.geomNodeTree) and not asset.geomNodeTree.getNodeByName("bone_turret"):
				heli = asset.geomNodeTree.getNodeByName("prop01_2") is not None and not any(n.name.startswith("aileron") for n in asset.geomNodeTree.getNodes())
				self.blk = {"fm": {}, **({"helicopter": True} if heli else {})}

			from util.wtloadout import presets, slotChoices, weaponLabels
			from util.i18n import LANGUAGE
			slots = slotChoices(self.blk or {})
			labels = weaponLabels(findGameRoot(asset.filePath), LANGUAGE, slots) if slots else {}
			self.weaponLabels = labels if slots else None
		except Exception as error:
			print(format_exc())
			MessageBox(str(error)).exec_()
			return False

		dialog = GlideOptionsDialog(self.mainWindow, defaultOptions(self.blk, asset.geomNodeTree), self.item.asset.name, presets(self.blk or {}), slots, self.previewLoadout, labels, findGameRoot(asset.filePath))

		if dialog.exec_() != QDialog.Accepted:
			return False

		self.options = dialog.options()
		self.vtfFormat = self.options.pop("vtfFormat", None)
		if self.vtfFormat in (VTF_FORMAT_DXT5, VTF_FORMAT_RGBA8888):
			SETTINGS.setValue(SETTINGS_VTF_FORMAT, self.vtfFormat)
		self.skinArchives = self.options.pop("skins", [])
		try:
			if self.options.get("aircraft", isAircraft(self.blk)):
				self.blk = dict(self.blk or {}, fm = (self.blk or {}).get("fm") or {})
				if self.options.get("helicopter"):
					self.blk["helicopter"] = True
				else:
					self.blk.pop("helicopter", None)

				if asset.collision is None:
					asset.setCollisionGeom(findAircraftCollision(asset.filePath, asset.name))

				self.keepBones = aircraftKeepBones(asset.geomNodeTree)

				try:
					self.a2d = A2D.fromPack(asset.filePath, f"{asset.name}_anim")
				except Exception as e: # no gear animation then, the gear stays as modelled
					log.log(f"War Thunder animation unreadable: {e}", 2)
			elif isAircraft(self.blk):
				self.blk = None
		except Exception as error:
			print(format_exc())
			MessageBox(str(error)).exec_()
			return False

		return SaveAction.preRun(self)

	def compileTargets(self, qc):
		if self.splitNozzles:
			from util.sourceparts import split
			parts = split(qc)
			name = self.item.asset.name
			targets = [(parts / "body.qc", name), (parts / "nozzles.qc", name + "_nozzles")]
		else:
			targets = super().compileTargets(qc)
		if self.loadout:
			from util.wtweapons import compileMissiles
			targets += compileMissiles(targets[0][0], self.loadout)
		if getattr(self, "smoke", None):
			targets += compileSmokeModels(targets[0][0], self.smdl.model.skeleton, self.smoke)
		return targets

	def prepareSourceModel(self, smdl):
		self.splitNozzles = False
		self.loadout = []
		self.smoke = None
		if isAircraft(self.blk):
			if self.options.get("loadout"):
				from util.wtloadout import apply
				self.loadout = apply(smdl.model, self.blk, self.options["loadout"], findGameRoot(self.item.asset.filePath), self.keepBones)
			else:
				smdl.model.removeObjects(aircraftHiddenNodes([o.name for o in smdl.model], self.blk))
			boneCount = len(smdl.model.skeleton.getReducedBones(self.keepBones)[0]) if smdl.model.skeleton else 0
			self.splitNozzles = boneCount > 256
			if self.splitNozzles:
				log.log(f"{boneCount} aircraft bones exceed Source's 256 limit; splitting body and animated nozzles")
			smdl.collisionNodeFilter = aircraftCollisionNodes
			self.surfaces = controlSurfaces(smdl.model)
			self.tracks = {"l": ((), 0.0), "r": ((), 0.0)}

			if self.a2d:
				smdl.sequences.update(gearSequences(smdl.model.skeleton, self.keepBones, self.a2d, self.blk.get("fm")))

			return

		smdl.collisionNodeFilter = glideCollisionNodes
		smdl.massCenter = tankMassCenter(self.blk, smdl.model.skeleton)
		smdl.model.removeObjects(hiddenNodes(self.blk, self.options["upgraded"]))
		self.tracks = splitTrackMaterials(smdl.model)
		try:
			self.smoke = prepareTankSmoke(self.blk, smdl.model, findGameRoot(self.item.asset.filePath), self.options["upgraded"])
		except Exception as error:
			log.log(f"Smoke launcher export skipped: {error}", 2)

	def save(self, output:str):
		asset:DynModel = self.item.asset
		super().save(output)

		if self.shouldTerminate:
			return

		self.setTaskStatus(tr("Writing Glide addon"))
		name = asset.name
		className = "wt_" + re.sub(r"[^a-z0-9_]", "_", name.lower())
		addonDir = path.join(path.dirname(SETTINGS.getValue(SETTINGS_GAMEINFO_PATH)), "addons", className)
		blk = self.blk

		if blk is None:
			log.log(f"No War Thunder tank blk found for {name}, using default stats")

		shutil.copytree(path.join(output, name, "source_export"), addonDir, dirs_exist_ok = True)
		matDir = path.join(addonDir, self.smdl.getMaterialsDir(self.modelPath))

		# right track meshes got their own material copy so both sides can scroll independently
		for mat in self.tracks["r"][0]:
			src = path.join(matDir, mat[:-len(TRACK_R_SUFFIX)] + ".vmt")

			if mat.endswith(TRACK_R_SUFFIX) and path.isfile(src):
				shutil.copyfile(src, path.join(matDir, mat + ".vmt"))

		skeleton = self.smdl.model.skeleton
		self.setTaskStatus(tr("Extracting War Thunder sounds"))
		writeAddon(addonDir, className, name.replace("_", " "), f"models/{self.modelPath}/{name}.mdl", skeleton, blk, self.tracks, self.options, findGameRoot(asset.filePath), self.a2d, self.surfaces, SETTINGS.getValue(SETTINGS_VTFCMD_PATH) or VTFCMD_PATH, nozzleModel = f"models/{self.modelPath}/{name}_nozzles.mdl" if self.splitNozzles else None, loadout = self.loadout, labels = getattr(self, "weaponLabels", None), smoke = getattr(self, "smoke", None))
		log.log(f"Glide addon written to {addonDir}")

class ExportLODsToSource(ExportToSource):
	def __init__(self, parent, item:SimpleItem):
		super().__init__(parent, item, 0)
	
	item:AssetItem

	@property
	def actionText(self) -> str:
		return tr("Export all LODs to Source engine")
	
	@property
	def taskTitle(self) -> str:
		return tr("Exporting all LODs from {name} to Source engine", name = self.item.asset.name)

	@classproperty
	def exportLODs(cls):
		return True

class ExportModel(AssetSaveAction):
	def __init__(self, parent, item:SimpleItem, lod:int = 0):
		self.lod = lod
		
		super().__init__(parent, item)

	def saveAsset(self, output:str, asset:RendInst):
		exportTex = not SETTINGS.getValue(SETTINGS_NO_TEX_EXPORT)
		forceConvert = SETTINGS.getValue(SETTINGS_FORCE_DDS_CONVERSION)

		mdl = asset.getModel(self.lod)

		if self.handleTermination(mdl):
			return
		
		getattr(mdl, self.exportMethodName)(output, exportTex, forceConvert)
	
	@property
	def actionText(self) -> str:
		return tr("Export LOD {lod} to {format}", lod = self.lod, format = self.exportFormat.upper())
	
	@property
	def taskTitle(self) -> str:
		return tr("Exporting LOD to {file}", file = f"{self.item.asset.getExportName(self.lod)}.{self.exportFormat}")
		
	@classproperty
	def exportMethodName(cls) -> str:
		raise NotImplementedError()
	
	@classproperty
	def exportFormat(cls) -> str:
		raise NotImplementedError()

class ExportLODs(PackedSave, ExportModel):
	@property
	def actionText(self) -> str:
		return tr("Export all LODs to {format}", format = self.exportFormat.upper())
	
	@property
	def taskTitle(self) -> str:
		return tr("Exporting all LODs from {name} to {format}", name = self.item.asset.name, format = self.exportFormat.upper())
	
	def save(self, output:str):
		asset:RendInst = self.item.asset

		output = self.makePackedOutputFolder(asset.name)

		self.setTerminable(asset)
		asset.computeData()

		for i in range(asset.lodCount):
			self.setTaskStatus(f"{self.getProgressText(asset)} LOD {i}/{asset.lodCount - 1}")

			self.lod = i

			if self.saveSingle(output, asset):
				break

			self.setTaskProgress((i + 1) / asset.lodCount)

		self.clearTerminable()

	def getProgressText(self, asset:Packed):
		return tr("Exporting {name}", name = asset.name)

class ExportAllModels(PackedSave, ExportModel):
	@classproperty
	def hasFilter(cls):
		return True

	def filter(self, asset):
		return isinstance(asset, RendInst)

	def getProgressText(self, asset:RendInst):
		return tr("Exporting {name}", name = f"{asset.getExportName(0)}.{self.exportFormat}")

	@property
	def actionText(self) -> str:
		return tr("Export all models to LOD 0 {format}", format = self.exportFormat.upper())
	
	@property
	def taskTitle(self) -> str:
		return tr("Exporting LOD 0 models from {file} to {format}", file = f"{self.item.asset.name}.{self.item.asset.fileExtension}", format = self.exportFormat.upper())


class ExportToDMF(ExportModel):
	@classproperty
	def exportMethodName(cls) -> str:
		return "exportDmf"

	@classproperty
	def exportFormat(cls) -> str:
		return "dmf"
	

class ExportSkeletonToDMF(ExportToDMF):
	@property
	def actionText(self):
		return tr("Export skeleton to {file}", file = f"{self.item.asset.name}.dmf")
	
	@property
	def taskTitle(self) -> str:
		return tr("Exporting skeleton to {file}", file = f"{self.item.asset.name}.{self.exportFormat}")

class ExportLODsToDMF(ExportToDMF, ExportLODs):
	def __init__(self, *args, **kwargs):
		super(ExportLODs, self).__init__(*args, **kwargs)

class ExportAllToDMF(ExportToDMF, ExportAllModels):
	def __init__(self, *args, **kwargs):
		super(ExportAllModels, self).__init__(*args, **kwargs)

class ExportToOBJ(ExportModel):
	@classproperty
	def exportMethodName(cls) -> str:
		return "exportObj"

	@classproperty
	def exportFormat(cls) -> str:
		return "obj"

class ExportLODsToOBJ(ExportToOBJ, ExportLODs):
	def __init__(self, *args, **kwargs):
		super(ExportLODs, self).__init__(*args, **kwargs)

class ExportAllToOBJ(ExportToOBJ, ExportAllModels):
	def __init__(self, *args, **kwargs):
		super(ExportAllModels, self).__init__(*args, **kwargs)



class FileSizeSortProxyModel(QSortFilterProxyModel):
	def lessThan(self, left, right):
		if left.column() == right.column() == 2: 
			leftData = self.sourceModel().data(left)
			rightData = self.sourceModel().data(right)

			if leftData is None:
				return False
			elif rightData is None:
				return True
			else:
				return int(leftData) < int(rightData)

		return super().lessThan(left, right)
	

class OptimizedModel(QStandardItemModel):
	__HEADER_LABELS = (tr("Name"), tr("Type"), tr("Size"))

	def __init__(self, parent:QTreeView, lineEdit:QLineEdit):
		super().__init__(parent)
		
		self.lineEdit = lineEdit
		self.lineEdit.textEdited.connect(self.textChanged)

		self.reset()
	
	def textChanged(self, text):
		self.proxyModel.setFilterRegExp(text)
	
	def reset(self):
		self.clear()

		self.setHorizontalHeaderLabels(OptimizedModel.__HEADER_LABELS)

		self.proxyModel = FileSizeSortProxyModel(self.parent())
		self.proxyModel.setSourceModel(self)
		self.proxyModel.setFilterCaseSensitivity(Qt.CaseInsensitive)
		self.proxyModel.setFilterKeyColumn(0)
		self.proxyModel.setRecursiveFilteringEnabled(True)

class FileSizeDelegate(QStyledItemDelegate):
	def displayText(self, value, locale):
		return formatBytes(int(value))

class CustomTreeView(QTreeView):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

		self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
		self.setContextMenuPolicy(Qt.CustomContextMenu)
		self.setAcceptDrops(True)
		self.setDragEnabled(True)
		self.setAlternatingRowColors(True)
		self.setUniformRowHeights(True)
		self.setAnimated(True)
		self.setIconSize(QSize(16, 16))
		self.mainWindow = None

		self.customContextMenuRequested.connect(self.rightClickEvent)
	
	def paintEvent(self, event:QPaintEvent):
		if self.model() and self.model().rowCount() > 0:
			super().paintEvent(event)
		else:
			painter = QPainter(self.viewport())
			painter.setPen(self.palette().color(QPalette.PlaceholderText))
			text = tr("Drag and drop files here or open assets through the \"File\" menu")
			textRect = painter.fontMetrics().boundingRect(text)
			textRect.moveCenter(self.viewport().rect().center())
			painter.drawText(textRect, Qt.AlignCenter, text)
	
	def rightClickEvent(self, pos:QPoint):
		index = self.indexAt(pos)
		item:SimpleItem = index.data(Qt.UserRole)

		# print((pos.x(), pos.y()), index.model())

		if item == None or not isinstance(item, SimpleItem): # TODO: add multi selection support
			return
		
		menu = QMenu()

		item.populateMenu(menu)

		action:CustomAction = menu.exec_(self.mapToGlobal(pos))

	def dropEvent(self, event:QDropEvent):
		paths = self.getEventPaths(event.mimeData())

		if paths:
			self.mainWindow.mountAssets(paths)
	
	def getEventPaths(self, data:QMimeData):
		if data.hasUrls():
			paths = [u.toLocalFile() for u in data.urls() if u.isLocalFile() and path.exists(u.toLocalFile())]
			return paths or None

		if data.hasText():
			paths = []

			for line in data.text().splitlines():
				fpath = line.strip()

				if not fpath:
					continue

				if fpath.startswith("file:///"):
					fpath = fpath[8:]

				if path.exists(fpath):
					paths.append(fpath)

			return paths or None
		
		return None
		
	def dragMoveEvent(self, event:QDragMoveEvent):
		if not self.getEventPaths(event.mimeData()):
			event.ignore()
		else:
			event.accept()

	def dragEnterEvent(self, event:QDragEnterEvent):
		if not self.getEventPaths(event.mimeData()):
			event.ignore()
		else:
			event.accept()
	
	def edit(self, index, trigger, event):
		if trigger == QAbstractItemView.DoubleClicked:
			return False
		else:
			return True

	def initModel(self, lineEdit:QLineEdit):
		self.treeModel = OptimizedModel(self, lineEdit)

		self.__reinitModel__()
		
	
	def __reinitModel__(self):
		self.setSortingEnabled(True)
		self.setModel(self.treeModel.proxyModel)

		header = self.header()
		header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
		header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
		header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
		
		header.setSortIndicator(0, Qt.AscendingOrder)
		self.setItemDelegateForColumn(2, FileSizeDelegate())


	def clear(self):
		self.treeModel.reset()
		
		self.__reinitModel__()
