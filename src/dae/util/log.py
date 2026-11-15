import sys
from os import path

sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))

from time import time
from util.enums import *
from threading import current_thread, local

startTime = time()

def getTime():
	return "%08.4f" % (time() - startTime)

_state = local()

def _getLevel() -> int:
	return getattr(_state, "curLevel", 0)

def incrLevel(level:int = 0):
	cur = max(0, _getLevel() + level)
	_state.curLevel = cur
	_state.levelStr = "    " * cur

def addLevel(level:int = 1):
	incrLevel(level)

def subLevel(level:int = 1):
	incrLevel(-level)

def getLevelStr():
	return getattr(_state, "levelStr", "")

def __getattr__(name:str):
	if name == "curLevel":
		return _getLevel()
	if name == "levelStr":
		return getLevelStr()
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

def log(message:str, type:int = 0):
	print(f"{getTime()} [{current_thread().ident}] ", end = "")

	if type == LOG_DEBUG: # could use a switch statement here
		print("[D]", end = "")
	elif type == LOG_ERROR:
		print("[E]", end = "")
	else:
		print("[W]", end = "")
	
	print(f" | {getLevelStr()}{message}")

	pass
