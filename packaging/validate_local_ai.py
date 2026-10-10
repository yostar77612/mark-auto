"""One explicitly authorized Windows/frozen free-AI validation, never a retry loop.

Two predeclared owned process phases: 300s official downloads/cache verification,
then 660s frozen setup/start/one original 1024-token/120s probe/cleanup. Each phase
has at most 10s additional supervisor cleanup. The existing CI job cap is unchanged.
Raw model/runtime files and SQLite attempt evidence remain outside deliverables.
"""
from __future__ import annotations
import argparse
import ctypes
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import struct
import subprocess
import sys
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from quantlab.local_ai import manifest, MANIFEST_SHA256, PROFILE, safe_path, verify_file, download
from quantlab.desktop_runtime import _WindowsProcessTree, atomic_write, _json_bytes

DOWNLOAD_SECONDS=300
FROZEN_SECONDS=660
CLEANUP_SECONDS=10
MAX_REPORT_BYTES=65536


@dataclass(frozen=True)
class Config:
    executable: Path
    cache: Path
    work: Path
    report: Path

    @property
    def attempt(self):return self.work/'attempt-state'
    @property
    def controller_report(self):return self.report.with_name('local-ai-ci.json')

    def validate(self, *, fresh=True):
        for path in (self.executable,self.cache,self.work,self.report):safe_path(path)
        verify_root=ROOT/'dist'/'validation'
        if not self.report.resolve().is_relative_to(verify_root.resolve()) or self.report.name!='local-ai-smoke.json':
            raise ValueError('Only fixed validation report destination is accepted')
        safe_path(self.executable,file=True)
        if self.executable.resolve() != (ROOT/'dist'/'MarkAuto'/'MarkAuto.exe').resolve():
            raise ValueError('Only this build frozen executable is accepted')
        for path in (self.cache,self.work):
            if path.resolve().is_relative_to(ROOT.resolve()):raise ValueError('Large data must stay outside checkout and artifacts')
        if self.cache.resolve().is_relative_to(self.work.resolve()) or self.work.resolve().is_relative_to(self.cache.resolve()):raise ValueError('Cache and attempt roots must be separate')
        if not fresh:return
        for destination in (self.report,self.report.with_suffix('.png'),self.controller_report,self.work/'attempt.json'):
            if destination.exists() or destination.is_symlink():raise ValueError('Existing attempt evidence cannot be replaced or retried')
        if self.work.exists() and any(self.work.iterdir()):raise ValueError('Existing work root is not retryable')


def read_json(path):
    safe_path(path,file=True)
    if path.stat().st_size>MAX_REPORT_BYTES:raise ValueError('Oversized report')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate report keys')
            result[key]=value
        return result
    value=json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=unique,
        parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite report')))
    if not isinstance(value,dict):raise ValueError('Report must be object')
    return value


def hash_file(path):
    safe_path(path,file=True)
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def verify_png(path):
    safe_path(path,file=True)
    if not 64<=path.stat().st_size<=16*1024*1024:raise ValueError('Invalid screenshot size')
    raw=path.read_bytes()
    if raw[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Screenshot is not PNG')
    offset=8;first=True;image_data=False;compressed=[];expected_bytes=None
    while offset+12<=len(raw):
        size=struct.unpack('>I',raw[offset:offset+4])[0]
        kind=raw[offset+4:offset+8];end=offset+12+size
        if end>len(raw):raise ValueError('Truncated PNG')
        payload=raw[offset+8:offset+8+size]
        if zlib.crc32(kind+payload)&0xffffffff!=struct.unpack('>I',raw[end-4:end])[0]:raise ValueError('PNG CRC mismatch')
        if first:
            if kind!=b'IHDR' or size!=13:raise ValueError('Missing PNG dimensions')
            width,height=struct.unpack('>II',payload[:8])
            if not 640<=width<=8192 or not 360<=height<=8192:raise ValueError('Native screenshot dimensions invalid')
            depth,color,compression,filter_method,interlace=payload[8:]
            if depth!=8 or color not in (2,6) or compression or filter_method or interlace:raise ValueError('Unsupported native PNG encoding')
            stride=width*(3 if color==2 else 4)+1;expected_bytes=stride*height
            if expected_bytes>64*1024*1024:raise ValueError('PNG expansion limit')
            first=False
        elif kind==b'IHDR':raise ValueError('Duplicate PNG dimensions')
        if kind==b'IDAT' and size:image_data=True;compressed.append(payload)
        if kind==b'IEND':
            if size or end!=len(raw) or not image_data:raise ValueError('Invalid PNG end')
            decoder=zlib.decompressobj()
            pixels=decoder.decompress(b''.join(compressed),expected_bytes+1)
            if len(pixels)!=expected_bytes or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise ValueError('Invalid or excessive PNG pixel stream')
            if any(pixels[row*stride]>4 for row in range(height)):raise ValueError('Invalid PNG row filter')
            return {'sha256':hashlib.sha256(raw).hexdigest(),'width':width,'height':height}
        offset=end
    raise ValueError('Missing PNG end')


def validate_result(config,exit_code):
    if exit_code!=0:raise ValueError('Frozen validation process failed')
    value=read_json(config.report);spec=manifest()
    required={'status':'passed','frozen':True,'platform':'win32','profile':PROFILE,
        'manifest_sha256':MANIFEST_SHA256,'model_calls':1,'cleanup_verified':True,
        'external_api_spend':'0','paid_fallback':False,'research_evaluations':0,
        'oos_or_holdout_access':False,'real_model_status':'not_verified',
        'clean_windows_client_status':'not_verified','native_window_screenshot_saved':True,
        'model_sha256':spec['model']['sha256'],'runtime_sha256':spec['runtime']['sha256'],
        'runtime_members_verified':len(spec['runtime_members']),'licenses_verified':len(spec['licenses']),
        'application_vc_dependencies_verified':len(spec['support_dlls'])}
    for key,expected in required.items():
        if type(value.get(key)) is not type(expected) or value[key]!=expected:raise ValueError('Native report gate mismatch: '+key)
    stages=value.get('stages',[])
    expected_stages=[('verified_setup',300),('owned_server_start',150),('one_schema_probe',135)]
    if not isinstance(stages,list) or len(stages)!=3:raise ValueError('Missing bounded stage evidence')
    for stage,(name,cap) in zip(stages,expected_stages):
        if (not isinstance(stage,dict) or stage.get('stage')!=name or stage.get('status')!='passed'
            or type(stage.get('cap_seconds')) is not int or stage['cap_seconds']!=cap
            or type(stage.get('seconds')) not in (int,float) or not 0<=stage['seconds']<=cap):
            raise ValueError('Invalid bounded stage evidence')
    owner=value.get('owned_server',{})
    if set(owner)!={'pid','created'} or any(type(owner[k]) is not int or owner[k]<=0 for k in owner):raise ValueError('Missing native process identity')
    modules=value.get('loaded_vc_runtime_modules',[])
    expected=[{'filename':name,'sha256':pin['sha256'],'loaded_from':'pinned_app_local_runtime'} for name,pin in spec['support_dlls'].items()]
    if not isinstance(modules,list) or any(not isinstance(v,dict) for v in modules) or sorted(modules,key=lambda v:v.get('filename',''))!=sorted(expected,key=lambda v:v['filename']):raise ValueError('Loaded module proof differs')
    probe=value.get('probe',{})
    if probe.get('status')!='schema_probe_pass' or probe.get('real_model_status')!='not_verified' or type(probe.get('research_evaluations')) is not int or probe['research_evaluations']!=0:raise ValueError('Missing actual schema probe')
    for key in ('response_hash','candidate_hash'):
        if not isinstance(probe.get(key),str) or not re.fullmatch('[0-9a-f]{64}',probe[key]):raise ValueError('Invalid probe hash')
    ledger=config.attempt/'control-v1'/'local-ai-v1.sqlite3';safe_path(ledger,file=True)
    db=sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True)
    try:
        budgets=db.execute('SELECT calls,tokens,spend FROM budget').fetchall()
        calls=db.execute('SELECT sequence,status,response_hash,reserved_tokens,reserved_spend FROM calls').fetchall()
    finally:db.close()
    if len(budgets)!=1 or type(budgets[0][0]) is not int or budgets[0][0]!=1 or type(budgets[0][1]) is not int or not 0<budgets[0][1]<=1000000 or budgets[0][2]!='0':raise ValueError('Permanent budget proof differs')
    if len(calls)!=1 or calls[0][0:3]!=(1,'transport_returned_not_verified',probe['response_hash']) or calls[0][3]!=budgets[0][1] or calls[0][4]!='0':raise ValueError('Permanent actual response receipt differs')
    expected_usage={'calls':1,'tokens':budgets[0][1],'max_calls':100,'max_tokens':1000000}
    if probe.get('usage')!=expected_usage or any(type(probe['usage'][key]) is not type(value) for key,value in expected_usage.items()):raise ValueError('UI receipt differs from ledger')
    screenshot=verify_png(config.report.with_suffix('.png'))
    return {'response_hash':probe['response_hash'],'candidate_hash':probe['candidate_hash'],
        'reserved_tokens':budgets[0][1],'screenshot':screenshot,'model_calls':1}


def download_phase(config):
    spec=manifest();config.cache.mkdir(parents=True,exist_ok=True)
    records={}
    for name in ('runtime','model'):
        pin=spec[name];target=config.cache/pin['filename'];hit=target.exists()
        # Existing bytes must verify; corrupt cache is not silently replaced.
        download(pin,target)
        verify_file(target,pin)
        records[name]={'sha256':pin['sha256'],'bytes':pin['bytes'],'cache_hit':hit}
    return records


def frozen_phase(config):
    spec=manifest()
    paths=[config.cache/spec[name]['filename'] for name in ('runtime','model')]
    for name,path in zip(('runtime','model'),paths):verify_file(path,spec[name])
    command=[str(config.executable),'--local-ai-smoke',str(config.report),
        '--local-ai-runtime-archive',str(paths[0]),'--local-ai-model',str(paths[1]),
        '--local-ai-root',str(config.attempt)]
    # This worker is already in the supervisor's verified Job Object. The frozen
    # program and its further children inherit it before executing any code.
    process=subprocess.Popen(command,shell=False,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,cwd=str(ROOT),creationflags=subprocess.CREATE_NO_WINDOW)
    code=process.wait()
    return validate_result(config,code)


def supervise(command,seconds):
    """Create suspended, assign owned kill-on-close tree, then resume; never adopt PID."""
    if sys.platform!='win32':raise RuntimeError('Windows supervisor required')
    from ctypes import wintypes as w
    class Startup(ctypes.Structure):
        _fields_=[('cb',w.DWORD),('reserved',w.LPWSTR),('desktop',w.LPWSTR),('title',w.LPWSTR),
            ('x',w.DWORD),('y',w.DWORD),('xsize',w.DWORD),('ysize',w.DWORD),('xcount',w.DWORD),('ycount',w.DWORD),
            ('fill',w.DWORD),('flags',w.DWORD),('show',w.WORD),('reserved2size',w.WORD),
            ('reserved2',ctypes.POINTER(ctypes.c_byte)),('stdin',w.HANDLE),('stdout',w.HANDLE),('stderr',w.HANDLE)]
    class Process(ctypes.Structure):
        _fields_=[('process',w.HANDLE),('thread',w.HANDLE),('pid',w.DWORD),('tid',w.DWORD)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateProcessW.argtypes=[w.LPCWSTR,w.LPWSTR,ctypes.c_void_p,ctypes.c_void_p,w.BOOL,w.DWORD,ctypes.c_void_p,w.LPCWSTR,ctypes.POINTER(Startup),ctypes.POINTER(Process)]
    kernel.CreateProcessW.restype=w.BOOL
    kernel.ResumeThread.argtypes=[w.HANDLE];kernel.ResumeThread.restype=w.DWORD
    kernel.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];kernel.WaitForSingleObject.restype=w.DWORD
    kernel.GetExitCodeProcess.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)]
    kernel.TerminateProcess.argtypes=[w.HANDLE,w.UINT];kernel.CloseHandle.argtypes=[w.HANDLE]
    startup=Startup();startup.cb=ctypes.sizeof(startup);process=Process();tree=None
    start=time.monotonic();result={'exit_code':None,'timed_out':False,'cleanup_verified':False}
    try:
        line=ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        if not kernel.CreateProcessW(command[0],line,None,None,False,0x08000004,None,str(ROOT),ctypes.byref(startup),ctypes.byref(process)):
            raise RuntimeError('Cannot create isolated validation worker')
        tree=_WindowsProcessTree(process.pid)
        if kernel.ResumeThread(process.thread)==0xffffffff:raise RuntimeError('Cannot resume owned worker')
        milliseconds=max(0,int((seconds-(time.monotonic()-start))*1000))
        wait=kernel.WaitForSingleObject(process.process,milliseconds)
        if wait==258:result['timed_out']=True
        elif wait!=0:raise RuntimeError('Cannot verify validation worker exit')
        else:
            code=w.DWORD()
            if not kernel.GetExitCodeProcess(process.process,ctypes.byref(code)):raise RuntimeError('Cannot read validation exit')
            result['exit_code']=code.value
    except Exception as exc:result['error_type']=type(exc).__name__
    finally:
        try:
            if tree is not None:
                tree.stop_and_join()  # bounded 6s native descendant proof
            elif process.process:
                # Assignment failed while the only child was still suspended.
                if not kernel.TerminateProcess(process.process,1):raise RuntimeError('Suspended worker cleanup failed')
            if process.process and kernel.WaitForSingleObject(process.process,3000)!=0:raise RuntimeError('Validation worker did not join')
            result['cleanup_verified']=True
        except Exception as exc:result['cleanup_error_type']=type(exc).__name__
        finally:
            if tree is not None:tree.close()
            if process.thread:kernel.CloseHandle(process.thread)
            if process.process:kernel.CloseHandle(process.process)
    result['seconds']=round(time.monotonic()-start,3)
    return result


def child_command(config,phase):
    return [sys.executable,str(Path(__file__).resolve()),'--internal-phase',phase,
        '--executable',str(config.executable),'--cache',str(config.cache),'--work',str(config.work),'--report',str(config.report)]


def run(config):
    config.validate()
    if sys.platform!='win32':raise RuntimeError('Native Windows required')
    config.work.mkdir(parents=True,exist_ok=True);config.report.parent.mkdir(parents=True,exist_ok=True)
    marker={'profile':PROFILE,'manifest_sha256':MANIFEST_SHA256,'download_cap_seconds':DOWNLOAD_SECONDS,
        'frozen_cap_seconds':FROZEN_SECONDS,'cleanup_cap_seconds_per_phase':CLEANUP_SECONDS,'retry':False}
    with (config.work/'attempt.json').open('x',encoding='utf-8') as stream:json.dump(marker,stream)
    result={**marker,'status':'failed','phases':{},'frozen_executable_sha256':hash_file(config.executable),
        'scope':'actual Windows Server frozen technical probe; not clean client or investment acceptance'}
    try:
        for phase,seconds in (('download',DOWNLOAD_SECONDS),('probe',FROZEN_SECONDS)):
            outcome=supervise(child_command(config,phase),seconds);result['phases'][phase]=outcome
            if outcome['timed_out'] or not outcome['cleanup_verified'] or outcome['exit_code']!=0 or outcome['seconds']>seconds+CLEANUP_SECONDS:raise RuntimeError('Controlled phase failed')
            phase_data=read_json(config.work/(phase+'-phase.json'))
            if phase_data.get('status')!='passed':raise RuntimeError('Worker phase failed')
            result['phases'][phase]['evidence']=phase_data['evidence']
        result['proof']=validate_result(config,0)
        result['status']='passed'
    except Exception as exc:result['error_type']=type(exc).__name__
    finally:atomic_write(config.controller_report,_json_bytes(result))
    return 0 if result['status']=='passed' else 1


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('executable','cache','work','report'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--internal-phase',choices=('download','probe'),help=argparse.SUPPRESS)
    args=parser.parse_args(argv);config=Config(args.executable,args.cache,args.work,args.report)
    if args.internal_phase:
        if sys.platform!='win32':return 1
        result={'status':'failed'};claimed=False
        phase_report=config.work/(args.internal_phase+'-phase.json')
        try:
            config.validate(fresh=False)
            if phase_report.exists():return 1
            if read_json(config.work/'attempt.json').get('manifest_sha256')!=MANIFEST_SHA256:raise ValueError('Missing authorized attempt marker')
            claim=config.work/(args.internal_phase+'-started.json')
            safe_path(claim)
            with claim.open('x',encoding='utf-8') as stream:json.dump({'phase':args.internal_phase,'retry':False},stream)
            claimed=True
            result['evidence']=(download_phase if args.internal_phase=='download' else frozen_phase)(config)
            result['status']='passed'
        except Exception as exc:result['error_type']=type(exc).__name__
        if claimed and not phase_report.exists():atomic_write(phase_report,_json_bytes(result))
        return 0 if result['status']=='passed' else 1
    try:return run(config)
    except Exception as exc:
        print('Local AI validation refused: '+type(exc).__name__)
        return 1


if __name__=='__main__':raise SystemExit(main())
