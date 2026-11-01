"""Run the real Beta 8.4 planner in the installed and staged frozen applications."""
from __future__ import annotations
import math

def verify():
    import numpy as np
    from tgc_transitional_background import (transition_scales, validate_transition_input,
                                             append_transitional_background)
    def check(value, message):
        if not value:
            raise RuntimeError('Beta 8.4 Graduated Background: '+message)
    for main in (1,2,3,4,6):
        check(tuple(transition_scales(main))==(64,32,4*main),
              'expected 64/32/%d m, main %d m'%(4*main,main))
    # A real red mask, plus a blue pond and NoData in the exterior. Keep the
    # native main area off-center to catch row/column or projected-origin mistakes.
    rr,cc=np.indices((240,308));z=(130.0+0.004*cc-0.003*rr).astype('float32')
    red=(cc<90)|(cc>138)|(rr<115)|(rr>160)
    blue=(rr>=120)&(rr<131)&(cc>=145)&(cc<156)
    bad=(rr>145)&(rr<156)&(cc>=157)&(cc<168)
    red[blue]=False;z[bad]=np.nan
    mask=np.zeros((z.shape[0],z.shape[1],3),dtype=np.uint8)
    mask[red,2]=255;mask[blue,0]=255
    detail=np.where(red|blue,np.nan,z)
    class Frame:
        def projToTGC(self,x,y,z):return x-2001.,z,y+702.
    for main in (1,3):
        result=[]
        validate_transition_input(z,mask,True)
        append_transitional_background(result,z,detail,mask,(2001.,-702.,1.),Frame(),
                                     main,lambda x,z,y,s,brush_type:(x,z,y,s,brush_type),
                                     printf=lambda *a:None)
        scales=[b[3] for b in result];s0=(64,32,4*main)
        check(tuple(dict.fromkeys(scales))==s0 and scales==sorted(scales,reverse=True),
              'wrong scales or write order on a red mask')
        found_seam=False
        for x,y,h,size,brush in result:
            i=int(math.floor(y));j=int(math.floor(x))
            check(brush==10 and 0<=i<z.shape[0] and 0<=j<z.shape[1] and red[i,j] and not blue[i,j] and
                  abs(h-float(z[i,j]))<0.0001, 'stamp not on a measured nonwater red cell')
            if size==4*main and 115<=i<=160 and j==89:found_seam=True
        check(found_seam or any(b[3]==4*main and 113<=b[1]<=161 and 86<=b[0]<=90 for b in result),
              'no fine-tier brush along the west seam')
    print('PASS: Beta 8.4 Graduated Background. Three ordered type-10 tiers; 4x seam; measured red-mask centers.')
    return True

if __name__=='__main__': verify()
