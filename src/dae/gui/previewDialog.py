import sys
from os import path

sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))

from io import BytesIO

import numpy as np
import util.log as log
from OpenGL import GL
from PIL import Image
from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import QPainter, QColor, QPen
from PyQt5.QtWidgets import QDialog, QOpenGLWidget
from PyQt5.uic import loadUi
from parse.material import DDSx, MaterialData, getBestTex
from parse.realres import Model
from util.assetcacher import AssetCacher
from util.i18n import translateUi, tr
from util.misc import getUIPath

PREVIEWUI_PATH = getUIPath("preview.ui")


class MeshPart:
	def __init__(self, positions:np.ndarray, uvs:np.ndarray, image:Image.Image = None, uvScale:tuple[float, float] = (1, 1)):
		self.positions = positions
		self.uvs = uvs
		self.image = image
		self.uvScale = uvScale

		a, b, c = positions[0::3], positions[1::3], positions[2::3]
		n = np.cross(b - a, c - a)
		n /= np.maximum(np.linalg.norm(n, axis = 1, keepdims = True), 1e-12)
		self.normals = np.repeat(n, 3, axis = 0).astype(np.float32)


def loadDiffuse(mat:MaterialData):
	tex = mat.diffuse

	if tex is None:
		return None

	ddsx = AssetCacher.getCachedAsset(DDSx, MaterialData.getTexFileName(tex))

	if not ddsx:
		log.log(f"Preview: texture {tex} not loaded")

		return None

	try:
		img = Image.open(BytesIO(getBestTex(mat, ddsx).getDDS()))
		# alpha holds masks in most Dagor shaders, not transparency
		img = img.convert("RGB").transpose(Image.FLIP_TOP_BOTTOM)

		return img
	except Exception as e:
		log.log(f"Preview: failed to decode {tex}: {e}")

		return None


def buildMeshParts(model:Model, loadTextures:bool = True):
	materials = {m.getName(): m for m in (model.materials or ())}
	skeleton = model.skeleton
	groups:dict[str, list[int, list]] = {}

	for obj in model:
		obj:Model.Object
		parentNode = skeleton.getNodeByName(obj.name) if skeleton is not None and not obj.skinned else None
		starts = sorted(obj.materials)

		for k, start in enumerate(starts):
			end = starts[k + 1] if k + 1 < len(starts) else obj.faceCount
			faces = obj.faces[start:end]

			if len(faces) == 0:
				continue

			ids = np.asarray(faces, dtype = np.int64).reshape(-1)
			uniq, inv = np.unique(ids, return_inverse = True)
			verts = np.array([model.getVertex(int(i), parentBone = parentNode) for i in uniq], dtype = np.float32)
			verts[:, 2] *= -1 # same handedness flip as OBJ export
			uvs = np.array([model.getUV(int(i))[:2] for i in uniq], dtype = np.float32)

			group = groups.setdefault(obj.materials[start], [[], []])
			group[0].append(verts[inv])
			group[1].append(uvs[inv])

	parts = []

	for matName, (verts, uvs) in groups.items():
		mat = materials.get(matName)
		image = None
		uvScale = (1, 1)

		if mat is not None and loadTextures:
			image = loadDiffuse(mat)

			if mat.detail1IsDiffuse():
				params = mat.getParams()
				uvScale = tuple(1 / float(params[k]) if k in params else 1 for k in ("detail1_tile_u", "detail1_tile_v"))

		parts.append(MeshPart(np.concatenate(verts), np.concatenate(uvs), image, uvScale))

	return parts


def projectMarker(position, modelview, projection, width, height):
	clip = projection @ modelview @ np.array((*position, 1.0))
	if clip[3] <= 0:
		return None
	x, y, z = clip[:3] / clip[3]
	if not -1 <= z <= 1:
		return None
	return ((x + 1) * width / 2, (1 - y) * height / 2)


class CustomOpenGL(QOpenGLWidget):
	def __init__(self, parent = None):
		super().__init__(parent)

		self.parts:list[MeshPart] = []
		self.textures:list[int] = []
		self.center = np.zeros(3, dtype = np.float32)
		self.radius = 1.0
		self.yaw = 45.0
		self.pitch = 20.0
		self.distance = 3.0
		self.lastPos = None
		self.markers = []

	def setParts(self, parts:list[MeshPart]):
		self.parts = parts

		if parts:
			allPos = np.concatenate([p.positions for p in parts])
			lo, hi = allPos.min(axis = 0), allPos.max(axis = 0)
			self.center = (lo + hi) / 2
			self.radius = max(float(np.linalg.norm(hi - lo)) / 2, 1e-3)

		self.distance = self.radius * 2.5
		self.update()

	def initializeGL(self):
		GL.glClearColor(0.25, 0.25, 0.28, 1)
		GL.glEnable(GL.GL_DEPTH_TEST)
		GL.glEnable(GL.GL_LIGHTING)
		GL.glEnable(GL.GL_LIGHT0)
		GL.glEnable(GL.GL_NORMALIZE)
		GL.glLightModeli(GL.GL_LIGHT_MODEL_TWO_SIDE, GL.GL_TRUE)
		GL.glLightfv(GL.GL_LIGHT0, GL.GL_AMBIENT, (0.35, 0.35, 0.35, 1))
		GL.glLightfv(GL.GL_LIGHT0, GL.GL_DIFFUSE, (0.75, 0.75, 0.75, 1))
		GL.glTexEnvi(GL.GL_TEXTURE_ENV, GL.GL_TEXTURE_ENV_MODE, GL.GL_MODULATE)

		for part in self.parts:
			if part.image is None:
				self.textures.append(0)

				continue

			tex = GL.glGenTextures(1)
			GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
			GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_REPEAT)
			GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_REPEAT)
			GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
			GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
			GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_GENERATE_MIPMAP, GL.GL_TRUE)
			alignment = GL.glGetIntegerv(GL.GL_UNPACK_ALIGNMENT)
			try:
				GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
				w, h = part.image.size
				GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB, w, h, 0, GL.GL_RGB, GL.GL_UNSIGNED_BYTE, part.image.tobytes())
			finally:
				# Qt's glyph atlas uploads require their original row alignment.
				GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, alignment)
			self.textures.append(tex)

	def resizeGL(self, w:int, h:int):
		GL.glViewport(0, 0, w, h)

	def paintGL(self):
		GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)

		GL.glMatrixMode(GL.GL_PROJECTION)
		GL.glLoadIdentity()
		aspect = max(self.width(), 1) / max(self.height(), 1)
		near = max(self.distance - self.radius * 2, self.radius * 0.01)
		top = near * 0.5 # ~53 degree vertical FOV
		GL.glFrustum(-top * aspect, top * aspect, -top, top, near, self.distance + self.radius * 2)

		GL.glMatrixMode(GL.GL_MODELVIEW)
		GL.glLoadIdentity()
		GL.glLightfv(GL.GL_LIGHT0, GL.GL_POSITION, (0.3, 0.5, 1, 0)) # headlight
		GL.glTranslatef(0, 0, -self.distance)
		GL.glRotatef(self.pitch, 1, 0, 0)
		GL.glRotatef(self.yaw, 0, 1, 0)
		GL.glTranslatef(*(-self.center))

		GL.glEnableClientState(GL.GL_VERTEX_ARRAY)
		GL.glEnableClientState(GL.GL_NORMAL_ARRAY)

		for part, tex in zip(self.parts, self.textures):
			if tex:
				GL.glEnable(GL.GL_TEXTURE_2D)
				GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
				GL.glEnableClientState(GL.GL_TEXTURE_COORD_ARRAY)
				GL.glTexCoordPointer(2, GL.GL_FLOAT, 0, part.uvs)
				GL.glMatrixMode(GL.GL_TEXTURE)
				GL.glLoadIdentity()
				GL.glScalef(part.uvScale[0], part.uvScale[1], 1)
				GL.glMatrixMode(GL.GL_MODELVIEW)
				GL.glMaterialfv(GL.GL_FRONT_AND_BACK, GL.GL_AMBIENT_AND_DIFFUSE, (1, 1, 1, 1))
			else:
				GL.glDisable(GL.GL_TEXTURE_2D)
				GL.glDisableClientState(GL.GL_TEXTURE_COORD_ARRAY)
				GL.glMaterialfv(GL.GL_FRONT_AND_BACK, GL.GL_AMBIENT_AND_DIFFUSE, (0.7, 0.7, 0.7, 1))

			GL.glVertexPointer(3, GL.GL_FLOAT, 0, part.positions)
			GL.glNormalPointer(GL.GL_FLOAT, 0, part.normals)
			GL.glDrawArrays(GL.GL_TRIANGLES, 0, len(part.positions))

		GL.glDisableClientState(GL.GL_TEXTURE_COORD_ARRAY)
		GL.glDisableClientState(GL.GL_NORMAL_ARRAY)
		GL.glDisableClientState(GL.GL_VERTEX_ARRAY)
		if self.markers:
			self.drawMarkers()

	def drawMarkers(self):
		modelview = np.asarray(GL.glGetDoublev(GL.GL_MODELVIEW_MATRIX)).T
		projection = np.asarray(GL.glGetDoublev(GL.GL_PROJECTION_MATRIX)).T
		GL.glPushAttrib(GL.GL_ALL_ATTRIB_BITS)
		painter = QPainter(self)
		try:
			painter.setRenderHint(QPainter.Antialiasing)
			font = painter.font()
			font.setBold(True)
			painter.setFont(font)
			used = []
			for index, pos, loaded in self.markers:
				point = projectMarker(pos, modelview, projection, self.width(), self.height())
				if point is None:
					continue
				x, y = point
				if not (0 <= x <= self.width() and 0 <= y <= self.height()):
					continue
				box = QRectF(x + 8, y - 30, 30, 24)
				box.moveLeft(min(box.left(), max(0, self.width() - box.width())))
				box.moveTop(max(28, min(box.top(), self.height() - box.height())))
				direction = 26 if box.center().y() < self.height() / 2 else -26
				while any(box.intersects(other) for other in used):
					box.translate(0, direction)
				used.append(box)
				color = QColor('#ffcb58' if loaded else '#9fddff')
				painter.setPen(QPen(color, 2))
				painter.drawLine(QPointF(x, y), box.center())
				painter.setBrush(color)
				painter.drawEllipse(QPointF(x, y), 3, 3)
				painter.setBrush(QColor(20, 25, 35, 225))
				painter.drawRoundedRect(box, 4, 4)
				painter.drawText(box, Qt.AlignCenter, str(index))
			painter.setPen(QColor('white'))
			painter.drawText(10, 20, tr('Hardpoints: yellow = loaded, blue = empty (shown through model)'))
		finally:
			painter.end()
			GL.glPopAttrib()

	def mousePressEvent(self, event):
		self.lastPos = event.pos()

	def mouseMoveEvent(self, event):
		if self.lastPos is None:
			return

		delta = event.pos() - self.lastPos
		self.lastPos = event.pos()

		if event.buttons() & Qt.LeftButton:
			self.yaw += delta.x() * 0.5
			self.pitch = max(-89.0, min(89.0, self.pitch + delta.y() * 0.5))
			self.update()

	def wheelEvent(self, event):
		self.distance *= 0.9 if event.angleDelta().y() > 0 else 1 / 0.9
		self.distance = max(self.distance, self.radius * 0.05)
		self.update()


class PreviewDialog(QDialog):
	def __init__(self, parent, title:str, parts:list[MeshPart], markers=()):
		super().__init__(parent)

		loadUi(PREVIEWUI_PATH, self)
		translateUi(self)

		self.setWindowTitle(title)
		self.setAttribute(Qt.WA_DeleteOnClose)
		self.gl:CustomOpenGL
		self.gl.markers = markers
		self.gl.setParts(parts)

