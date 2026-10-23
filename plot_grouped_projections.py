"""Render reproducible MIP references and quantify threshold-induced changes."""
import json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw

def build():
    out=Path('experiments/grouped-results');out.mkdir(exist_ok=True)
    for name,suffix,window in [('bonsai','32',255),('foot','32',255),('engine','32',255),('kingsnake','40',255),('woodbranch','5000',12000)]:
        root=Path('experiments/large-volumes')/(name+suffix)
        m=json.loads((root/'metadata.json').read_text())
        sheet=Image.new('RGB',(990,1070),'#101820');draw=ImageDraw.Draw(sheet)
        draw.text((12,10),f"{name} | full-resolution MIP (not DVR) | cutoff >{m['cutoff']} | display 0..{window}",fill='white')
        for x,label in enumerate(['Original (no cutoff)','Original with selection cutoff','Decoded export (verified exact)']):
            draw.text((12+x*330,38),label,fill='white')
        loss=[]
        for axis in range(3):
            original=np.load(root/f'original-mip-{axis}.npy')
            selected=np.load(root/f'threshold-mip-{axis}.npy')
            decoded=np.load(root/f'export-mip-{axis}.npy')
            loss.append(dict(axis=axis,pixels=original.size,changed_by_selection=int(np.count_nonzero(original!=selected)),
                             target_vs_export_different_pixels=int(np.count_nonzero(selected!=decoded))))
            for col,a in enumerate([original,selected,decoded]):
                im=Image.fromarray((np.clip(a.astype(np.float32)/window,0,1)*255).astype(np.uint8))
                im.thumbnail((318,310))
                sheet.paste(im,(col*330+(330-im.width)//2,82+axis*330+(310-im.height)//2))
            draw.text((12,65+axis*330),f'Axis {axis}',fill='#a8c9df')
        sheet.save(out/(name+'-projections.png'))
        (out/(name+'-projection-loss.json')).write_text(json.dumps(loss,indent=2)+'\n')
if __name__=='__main__':build()
