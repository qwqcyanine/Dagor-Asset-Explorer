
import sys
from os import path

sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))

from json import loads, dumps
import shutil
from util.decompression import lzmaCompress, lzmaDecompress
from util.misc import ROOT_FOLDER
from util.enums import *
import util.log as log

compressSettings = False

class Settings:
	__DEFAULT_SETTINGS = {
		SETTINGS_EXPORT_FOLDER:True,
		SETTINGS_EXPORT_PREVIEW_TEX:False,
		SETTINGS_EXTRACT_FOLDER:True,
		SETTINGS_NO_TEX_EXPORT:False,
		SETTINGS_OUTPUT_FOLDER:False,
		SETTINGS_EXPORT_GAMEINFO:False,
		SETTINGS_STUDIOMDL_PATH:"",
		SETTINGS_VTFCMD_PATH:"",
		SETTINGS_GAMEINFO_PATH:"",
		SETTINGS_STUDIOMDL_EXPORT_COLLISION:False,
		SETTINGS_EXPORT_SMD:True,
		SETTINGS_NO_MDL:False,
		SETTINGS_DONT_EXPORT_EXISTING_TEXTURES:False,
		SETTINGS_FORCE_DDS_CONVERSION:True,
		SETTINGS_EXPAND_ALL:False,
		SETTINGS_LANGUAGE:"auto",
		SETTINGS_THEME:THEME_DARK,
		SETTINGS_VTF_FORMAT:VTF_FORMAT_DXT5,
	}

	def saveSettings(self):
		f = open(self.__fpath, "wb")
		
		if compressSettings:
			f.write(lzmaCompress(dumps(self.__settings, indent = 4)))
		else:
			f.write(dumps(self.__settings, indent = 4).encode("utf-8"))
			
		f.close()

	def saveSettingsDecompressed(self):
		f = open(self.__fpath + ".json", "w")
		
		f.write(dumps(self.__settings, indent = 4))

		f.close()
	
	def getSettings(self):
		return self.__settings
	
	def getValue(self, setting):
		return self.__settings[setting]
	
	def setValue(self, setting, val):
		self.__settings[setting] = val

		self.saveSettings()
	
	def resetSettings(self):
		self.__settings = dict(self.__DEFAULT_SETTINGS)

		self.saveSettings()

	
	def loadSettings(self):
		fpath = self.__fpath
		
		if not path.isfile(fpath):
			self.resetSettings()
		else:
			try:
				with open(fpath, "rb") as f:
					raw = f.read()

				if compressSettings:
					settings = loads(lzmaDecompress(raw))
				else:
					settings = loads(raw.decode("utf-8"))

				if not isinstance(settings, dict):
					raise ValueError("Settings root must be a JSON object")
				
				settingsKeys = settings.keys()

				shouldSave = False

				for k in self.__DEFAULT_SETTINGS:
					v = self.__DEFAULT_SETTINGS[k]

					if not k in settingsKeys or type(v) != type(settings[k]):
						shouldSave = True

						settings[k] = v
						
				self.__settings = settings

				if shouldSave == True:
					self.saveSettings()
			except Exception as exc:
				try:
					shutil.copy2(fpath, fpath + ".bak")
				except OSError:
					pass
				log.log(f"Failed to load settings from {fpath} ({exc}); backed up to {fpath}.bak and reset", LOG_WARN)
				self.resetSettings()
	
	def __init__(self):
		fpath = ROOT_FOLDER + "\\settings.json"
		
		self.__fpath = fpath

		self.loadSettings()

SETTINGS = Settings()
# settings.saveSettingsDecompressed()