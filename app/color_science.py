"""Float RGB/XYZ adaptation and reversible working/output color transforms.

Working space is linear ProPhoto D50. Intermediate negative/over-one samples
are retained. ICC matrix profiles are generated from the same matrices/TRCs
used for numerical conversion, rather than relabelling sRGB pixels.
"""
import struct,datetime
from functools import lru_cache
import numpy as np

D65=np.array([.95047,1,1.08883]);D50=np.array([.96422,1,.82521])
BRADFORD=np.array([[.8951,.2664,-.1614],[-.7502,1.7135,.0367],[.0389,-.0685,1.0296]])
SPACES={
 'sRGB':(np.array([[.4124564,.3575761,.1804375],[.2126729,.7151522,.0721750],[.0193339,.1191920,.9503041]]),D65,'srgb'),
 'AdobeRGB':(np.array([[.5767309,.1855540,.1881852],[.2973769,.6273491,.0752741],[.0270343,.0706872,.9911085]]),D65,'adobe'),
 'ProPhoto':(np.array([[.7976749,.1351917,.0313534],[.2880402,.7118741,.0000857],[0,0,.8252100]]),D50,'prophoto'),
 'Rec2020':(np.array([[.6369580,.1446169,.1688810],[.2627002,.6779981,.0593017],[0,.0280727,1.0609851]]),D65,'rec2020')}

def adaptation(source,destination):
    return np.linalg.inv(BRADFORD)@np.diag((BRADFORD@destination)/(BRADFORD@source))@BRADFORD

@lru_cache(maxsize=24)
def matrix(source,destination):
    sm,sw,_=SPACES[source];dm,dw,_=SPACES[destination]
    return (np.linalg.inv(dm)@adaptation(sw,dw)@sm).astype(np.float32)

def convert_linear(rgb,source='sRGB',destination='ProPhoto'):
    if source==destination:return np.asarray(rgb,np.float32)
    return np.asarray(rgb,np.float32)@matrix(source,destination).T

def decode(rgb,space='sRGB'):
    x=np.asarray(rgb,np.float32);a=np.abs(x);kind=SPACES[space][2]
    if kind=='srgb':y=np.where(a<=.04045,a/12.92,((a+.055)/1.055)**2.4)
    elif kind=='adobe':y=a**(563/256)
    elif kind=='prophoto':y=np.where(a<=16/512,a/16,a**1.8)
    else:y=np.where(a<.08145,a/4.5,((a+.0993)/1.0993)**(1/.45))
    return np.copysign(y,x).astype(np.float32)

def encode(rgb,space='sRGB'):
    x=np.asarray(rgb,np.float32);a=np.abs(x);kind=SPACES[space][2]
    if kind=='srgb':y=np.where(a<=.0031308,a*12.92,1.055*a**(1/2.4)-.055)
    elif kind=='adobe':y=a**(256/563)
    elif kind=='prophoto':y=np.where(a<=1/512,a*16,a**(1/1.8))
    else:y=np.where(a<.0181,a*4.5,1.0993*a**.45-.0993)
    return np.copysign(y,x).astype(np.float32)

def from_srgb(rgb255):return convert_linear(decode(np.asarray(rgb255,np.float32)/255),'sRGB','ProPhoto')
def to_srgb(working):return encode(convert_linear(working,'ProPhoto','sRGB'))*255

M1=np.array([[.4122214708,.5363325363,.0514459929],[.2119034982,.6806995451,.1073969566],[.0883024619,.2817188376,.6299787005]],np.float32)
M2=np.array([[.2104542553,.7936177850,-.0040720468],[1.9779984951,-2.4285922050,.4505937099],[.0259040371,.7827717662,-.8086757660]],np.float32)
I1=np.linalg.inv(M1).astype(np.float32);I2=np.linalg.inv(M2).astype(np.float32)
def oklab(linear_srgb):return np.cbrt(np.asarray(linear_srgb,np.float32)@M1.T)@M2.T
def oklab_rgb(lab):return ((np.asarray(lab,np.float32)@I2.T)**3)@I1.T

def white_xyz(kelvin):
    t=float(kelvin)
    if t<=4000:x=-.2661239e9/t**3-.2343589e6/t**2+.8776956e3/t+.179910
    else:x=-3.0258469e9/t**3+2.1070379e6/t**2+.2226347e3/t+.240390
    if t<=2222:y=-1.1063814*x**3-1.34811020*x**2+2.18555832*x-.20219683
    elif t<=4000:y=-.9549476*x**3-1.37418593*x**2+2.09137015*x-.16748867
    else:y=3.081758*x**3-5.8733867*x**2+3.75112997*x-.37001483
    return np.array([x/y,1,(1-x-y)/y])

def temperature_matrix(kelvin=6500,tint=0):
    # Relative illuminant adjustment; raw camera multipliers remain separate.
    base=white_xyz(6500);target=white_xyz(kelvin)
    m=np.linalg.inv(SPACES['ProPhoto'][0])@adaptation(base,target)@SPACES['ProPhoto'][0]
    m=np.diag([np.exp(tint*.0008),np.exp(-tint*.0016),np.exp(tint*.0008)])@m
    return m.astype(np.float32)

def _fixed(x):return struct.pack('>i',round(float(x)*65536))
def _xyz(v):return b'XYZ '+b'\0'*4+b''.join(_fixed(x) for x in v)

@lru_cache(maxsize=12)
def icc_profile(space='sRGB',linear=False):
    if space not in SPACES:raise ValueError('Unknown output color space')
    mat,white,_=SPACES[space];mat=adaptation(white,D50)@mat
    trc=np.linspace(0,1,4096,dtype=np.float32)
    values=trc if linear else decode(trc,space)
    curve=(b'curv'+b'\0'*4+struct.pack('>IH',1,256)) if linear else b'curv'+b'\0'*4+struct.pack('>I',len(values))+np.rint(values*65535).astype('>u2').tobytes()
    description=('AURA '+space+(' Linear' if linear else '')).encode('ascii')+b'\0'
    desc=b'desc'+b'\0'*4+struct.pack('>I',len(description))+description+b'\0'*78
    tags=[(b'desc',desc),(b'cprt',b'text'+b'\0'*4+b'AURA matrix/TRC profile\0'),(b'wtpt',_xyz(D50))]
    for i,c in enumerate(b'rgb'):tags.append((bytes([c])+b'XYZ',_xyz(mat[:,i])));tags.append((bytes([c])+b'TRC',curve))
    offset=128+4+12*len(tags);entries=[];body=bytearray()
    for signature,payload in tags:
        entries.append(signature+struct.pack('>II',offset+len(body),len(payload)));body.extend(payload);body.extend(b'\0'*((-len(body))%4))
    header=bytearray(128);header[4:8]=b'AURA';header[8:12]=struct.pack('>I',0x02100000)
    header[12:16]=b'mntr';header[16:20]=b'RGB ';header[20:24]=b'XYZ '
    header[24:36]=struct.pack('>6H',2026,10,8,0,0,0);header[36:40]=b'acsp';header[40:44]=b'MSFT'
    header[68:80]=b''.join(_fixed(x) for x in D50);header[80:84]=b'AURA'
    data=header+struct.pack('>I',len(tags))+b''.join(entries)+body;data[:4]=struct.pack('>I',len(data))
    return bytes(data)
