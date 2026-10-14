"""Small offline sky network on the shared PyTorch device.

Sky weights: xiongzhu666, MIT. Person masks use MediaPipe separately.
No torchvision installation, remote code, pickle objects, or auto-downloads.
"""
from pathlib import Path
from collections import Counter
import hashlib,struct
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

ROOT=Path(__file__).resolve().parent/'models/scene'
HASHES={'skysegsmall_sim-opt-fp16.param':'7af3523130445db42d94503558c08ce991932f843b92e4e921c99d732768895e',
 'skysegsmall_sim-opt-fp16.bin':'ff1e18f71dc0a0cf8a56b634c59f68d296deffd015cbed27a6d5e302f991faf2'}

def asset(name):
    path=ROOT/name
    if not path.is_file():raise ValueError('缺少 AI 分区模型：'+name)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=HASHES[name]:raise ValueError('AI 分区模型校验失败：'+name)
    return path

class SkyNetwork(nn.Module):
    """Read the pinned NCNN graph as a bounded set of Torch operators."""
    def __init__(self):
        super().__init__();self.nodes=[];self.convs=nn.ModuleDict();self.uses=Counter()
        rows=asset('skysegsmall_sim-opt-fp16.param').read_text().splitlines()
        if rows[:2]!=['7767517','331 403']:raise ValueError('天空模型图结构无效。')
        binary=asset('skysegsmall_sim-opt-fp16.bin').read_bytes();offset=0
        for row in rows[2:]:
            fields=row.split();kind,name=fields[:2];ni,no=map(int,fields[2:4]);inputs=fields[4:4+ni];outputs=fields[4+ni:4+ni+no]
            params={int(k):float(v) for k,v in (x.split('=') for x in fields[4+ni+no:])}
            if kind not in ('Input','Convolution','Split','Concat','Interp','Pooling','BinaryOp','Sigmoid'):raise ValueError('天空模型算子无效。')
            self.uses.update(inputs);self.nodes.append((kind,name,inputs,outputs,params))
            if kind=='Convolution':
                out=int(params[0]);kernel=int(params.get(1,1));count=int(params[6]);inc=count//out//kernel**2
                tag=struct.unpack_from('<I',binary,offset)[0];offset+=4
                if tag!=0x01306b47:raise ValueError('天空模型权重编码无效。')
                weight=np.frombuffer(binary,dtype='<f2',count=count,offset=offset).astype(np.float32);offset=(offset+count*2+3)//4*4
                bias=np.frombuffer(binary,dtype='<f4',count=out,offset=offset).copy();offset+=out*4
                conv=nn.Conv2d(inc,out,kernel,stride=int(params.get(3,1)),padding=int(params.get(4,0)),dilation=int(params.get(2,1)),bias=True)
                conv.weight.data.copy_(torch.from_numpy(weight.reshape(out,inc,kernel,kernel)));conv.bias.data.copy_(torch.from_numpy(bias));self.convs[name]=conv
        if offset!=len(binary):raise ValueError('天空模型权重长度无效。')
    def forward(self,x):
        values={'input.1':x};uses=self.uses.copy()
        for kind,name,inputs,outputs,p in self.nodes:
            if kind=='Input':continue
            args=[values[k] for k in inputs];a=args[0]
            if kind=='Convolution':
                result=self.convs[name](a);activation=int(p.get(9,0))
                if activation==1:result=F.relu(result)
                elif activation==4:result=torch.sigmoid(result)
                elif activation:raise ValueError('天空模型激活类型无效。')
            elif kind=='Split':result=a
            elif kind=='Concat':result=torch.cat(args,dim=1)
            elif kind=='Interp':result=F.interpolate(a,size=(int(p[3]),int(p[4])),mode='bilinear',align_corners=False)
            elif kind=='Pooling':result=F.max_pool2d(a,int(p.get(1,2)),int(p.get(2,2)),ceil_mode=True)
            elif kind=='BinaryOp':result=args[0]+args[1]
            else:result=torch.sigmoid(a)
            for key in outputs:values[key]=result
            for key in inputs:
                uses[key]-=1
                if uses[key]==0:values.pop(key,None)
            if '1959' in outputs:return result
        raise ValueError('天空模型缺少输出。')
