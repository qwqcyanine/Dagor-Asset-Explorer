import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/dae'))
from util.wtloadout import hardpointMarkers, apply
from gui.previewDialog import projectMarker, CustomOpenGL
from PIL import Image
from parse.realres import Model

class PreviewMarkersTest(unittest.TestCase):
    def test_selected_and_empty_native_positions(self):
        a={'name':'a','Weapon':{'emitter':'left'}}
        b={'name':'b','Weapon':[{'emitter':'left'},{'emitter':'right'},{'emitter':'ignored','dummy':True}]}
        blk={'WeaponSlots':{'WeaponSlot':[{'index':1,'WeaponPreset':[a,b]},{'index':12,'WeaponPreset':a}]}}
        nodes={name:SimpleNamespace(wtm=np.array([[1,0,0,x],[0,1,0,2],[0,0,1,3],[0,0,0,1]])) for name,x in [('left',-4),('right',4)]}
        skeleton=SimpleNamespace(getNodeByName=nodes.get)
        markers=hardpointMarkers(blk,skeleton,[(1,b)])
        self.assertEqual(markers,[(1,(0,2,-3),True),(12,(-4,2,-3),False)])
        self.assertEqual(hardpointMarkers(blk,None),[])

    def test_texture_upload_restores_pixel_alignment(self):
        image=Image.new('RGB',(63,65))
        for alignment in (4,8):
            for fail in (False,True):
                with self.subTest(alignment=alignment,fail=fail), patch('gui.previewDialog.GL') as gl:
                    gl.glGetIntegerv.return_value=alignment
                    gl.glTexImage2D.side_effect=RuntimeError('upload failed') if fail else None
                    widget=SimpleNamespace(parts=[SimpleNamespace(image=image)],textures=[])
                    if fail:
                        with self.assertRaisesRegex(RuntimeError,'upload failed'):
                            CustomOpenGL.initializeGL(widget)
                    else:
                        CustomOpenGL.initializeGL(widget)
                    self.assertEqual([c.args for c in gl.glPixelStorei.call_args_list],
                        [(gl.GL_UNPACK_ALIGNMENT,1),(gl.GL_UNPACK_ALIGNMENT,alignment)])

    def test_screen_projection(self):
        identity=np.eye(4)
        self.assertEqual(projectMarker((0,0,0),identity,identity,800,600),(400,300))
        self.assertEqual(projectMarker((1,1,0),identity,identity,800,600),(800,0))
        self.assertIsNone(projectMarker((0,0,2),identity,identity,800,600))
        behind=identity.copy();behind[3,3]=-1
        self.assertIsNone(projectMarker((0,0,0),identity,behind,800,600))
        moved=identity.copy();moved[0,3]=.5
        self.assertEqual(projectMarker((0,0,0),moved,identity,800,600),(600,300))

    def test_preview_allows_retarded_bomb_export_still_rejects(self):
        weapon={'blk':'bomb','emitter':'mount','trigger':'bombs','bullets':1}
        blk={'WeaponSlots':{'WeaponSlot':{'index':1,'WeaponPreset':{'name':'test','Weapon':weapon}}}}
        data={'bomb':{'mesh':'bomb','shotFreq':1,'bomb':{'mass':100,'explosiveMass':10,'brakeTime':1}},'config/gameplay.blk':{}}
        node=SimpleNamespace(name='mount',idx=0,wtm=np.eye(4))
        model=Model('plane',skeleton=SimpleNamespace(getNodeByName=lambda n:node))
        with patch('util.vromfs.VROMFS') as vfs,patch('util.wtloadout.loadModels',return_value={'bomb':Model('bomb')}):
            vfs.return_value.readBlk.side_effect=lambda p:data[p]
            self.assertEqual(len(apply(model,blk,{1:'test'},'game',set(),previewOnly=True)),1)
            with self.assertRaisesRegex(ValueError,'Guided/retarded'):
                apply(model,blk,{1:'test'},'game',set())

if __name__=='__main__':unittest.main()
