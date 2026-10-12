using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
public sealed class MarkAutoAcceptanceJob : IDisposable {
    IntPtr job, process;
    [StructLayout(LayoutKind.Sequential)] struct MemoryStatus {
        public uint length, load; public ulong totalPhysical, availablePhysical, totalPage, availablePage, totalVirtual, availableVirtual, extendedVirtual;
    }
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GlobalMemoryStatusEx(ref MemoryStatus status);
    public static ulong FreeMemoryBytes() { MemoryStatus s=new MemoryStatus(); s.length=(uint)Marshal.SizeOf(typeof(MemoryStatus)); Check(GlobalMemoryStatusEx(ref s)); return s.availablePhysical; }
    [StructLayout(LayoutKind.Sequential)] struct Limits {
        public long processTime, jobTime; public uint flags; public UIntPtr min, max;
        public uint active; public UIntPtr affinity; public uint priority, scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] struct ExtendedLimits {
        public Limits basic; public ulong readOps, writeOps, otherOps, readBytes, writeBytes, otherBytes;
        public UIntPtr processMemory, jobMemory, peakProcessMemory, peakJobMemory;
    }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct Startup {
        public int cb; public string reserved, desktop, title;
        public uint x,y,width,height,charsX,charsY,fill,flags; public ushort show, reservedSize;
        public IntPtr reservedData, input, output, error;
    }
    [StructLayout(LayoutKind.Sequential)] struct StartupEx { public Startup start; public IntPtr attributes; }
    [StructLayout(LayoutKind.Sequential)] struct ProcessInfo { public IntPtr process, thread; public uint id, threadId; }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr CreateJobObject(IntPtr security, string name);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr OpenJobObject(uint access, bool inherit, string name);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetInformationJobObject(IntPtr job, int info, ref ExtendedLimits limits, uint size);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool InitializeProcThreadAttributeList(IntPtr list, int count, int flags, ref IntPtr size);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool UpdateProcThreadAttribute(IntPtr list, uint flags, IntPtr attribute, IntPtr value, IntPtr size, IntPtr previous, IntPtr returned);
    [DllImport("kernel32.dll")] static extern void DeleteProcThreadAttributeList(IntPtr list);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool CreateProcess(string app, StringBuilder command, IntPtr ps, IntPtr ts, bool inherit, uint flags, IntPtr environment, string directory, ref StartupEx startup, out ProcessInfo info);
    [DllImport("kernel32.dll", EntryPoint="CreateProcessW", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)] static extern bool CreateProcessBasic(string app, StringBuilder command, IntPtr ps, IntPtr ts, bool inherit, uint flags, IntPtr environment, string directory, ref Startup startup, out ProcessInfo info);
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint GetProcessId(IntPtr handle);
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool IsProcessInJob(IntPtr process, IntPtr job, out bool result);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateJobObject(IntPtr job, uint code);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateProcess(IntPtr process, uint code);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetExitCodeProcess(IntPtr process, out uint code);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetProcessTimes(IntPtr process, out long created, out long exited, out long kernel, out long user);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool QueryFullProcessImageName(IntPtr process, uint flags, StringBuilder path, ref int size);
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    [StructLayout(LayoutKind.Sequential)] struct FileInfo {
        public uint attributes, creationLow, creationHigh, accessLow, accessHigh, writeLow, writeHigh;
        public uint volume, sizeHigh, sizeLow, links, indexHigh, indexLow;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr CreateFile(string path, uint access, uint sharing, IntPtr security, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetFileInformationByHandle(IntPtr file, out FileInfo info);
    public static uint PathAttributes(string path) {
        // Require an actual metadata-read handle. Directory enumeration alone can expose
        // attributes even when the target's FILE_READ_ATTRIBUTES permission is denied.
        IntPtr file=CreateFile(path,0x80,7,IntPtr.Zero,3,0x02200000,IntPtr.Zero);
        if(file==new IntPtr(-1)) {
            int error=Marshal.GetLastWin32Error();
            if(error==2 || error==3) return 0xffffffff; // Only verified FILE/PATH_NOT_FOUND means absent.
            throw new Win32Exception(error);
        }
        try { FileInfo info; Check(GetFileInformationByHandle(file,out info)); return info.attributes; }
        finally { CloseHandle(file); }
    }
    [StructLayout(LayoutKind.Sequential)] struct Accounting {
        public long totalUser, totalKernel, periodUser, periodKernel;
        public uint faults, totalProcesses, activeProcesses, terminatedProcesses;
    }
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool QueryInformationJobObject(IntPtr job, int info, out Accounting data, uint size, IntPtr returned);
    static uint ActiveCount(IntPtr handle) {
        // NULL would query the caller's unrelated containing job. Fail closed instead.
        if(handle==IntPtr.Zero || handle==new IntPtr(-1)) throw new InvalidOperationException("Owned job handle is unavailable");
        Accounting data; Check(QueryInformationJobObject(handle,1,out data,(uint)Marshal.SizeOf(typeof(Accounting)),IntPtr.Zero));
        return data.activeProcesses;
    }
    public uint ActiveProcesses { get { return ActiveCount(job); } }
    public static uint OwnedActiveProcesses(string name) {
        IntPtr owned=OpenJobObject(4,false,name);
        if(owned==IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
        try { return ActiveCount(owned); } finally { CloseHandle(owned); }
    }
    static void Check(bool ok) { if (!ok) throw new Win32Exception(Marshal.GetLastWin32Error()); }
    static void Check(bool ok, string phase) {
        if(!ok) { var error=new Win32Exception(Marshal.GetLastWin32Error()); error.Data["acceptance_phase"]=phase; throw error; }
    }
    public MarkAutoAcceptanceJob(string name) {
        job = CreateJobObject(IntPtr.Zero, name);
        if (job == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
        if (Marshal.GetLastWin32Error() == 183) { Dispose(); throw new InvalidOperationException("Job name already exists"); }
        try {
            ExtendedLimits limits=new ExtendedLimits(); limits.basic.flags=0x2000; // KILL_ON_JOB_CLOSE; no breakaway
            Check(SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf(typeof(ExtendedLimits))));
        } catch { Dispose(); throw; }
    }
    ~MarkAutoAcceptanceJob() { Dispose(); }
    public void Start(string executable, string arguments) {
        if(job==IntPtr.Zero || process!=IntPtr.Zero) throw new InvalidOperationException("Invalid job launch state");
        IntPtr attributes=IntPtr.Zero, value=IntPtr.Zero;
        bool initialized=false;
        ProcessInfo pi=new ProcessInfo();
        try {
            IntPtr size=IntPtr.Zero;
            InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref size);
            attributes=Marshal.AllocHGlobal(size);
            Check(InitializeProcThreadAttributeList(attributes, 1, 0, ref size)); initialized=true;
            value=Marshal.AllocHGlobal(IntPtr.Size); Marshal.WriteIntPtr(value,job);
            // Windows 10+ JOB_LIST assigns ownership atomically at process creation.
            // Even cancellation between creation and resume cannot orphan an unowned worker.
            Check(UpdateProcThreadAttribute(attributes,0,new IntPtr(0x2000D),value,new IntPtr(IntPtr.Size),IntPtr.Zero,IntPtr.Zero));
            StartupEx start=new StartupEx(); start.start.cb=Marshal.SizeOf(typeof(StartupEx)); start.attributes=attributes;
            Check(CreateProcess(executable,new StringBuilder("\""+executable+"\" "+arguments),IntPtr.Zero,IntPtr.Zero,false,0x00080004,IntPtr.Zero,null,ref start,out pi));
            process=pi.process;
            Check(ResumeThread(pi.thread)!=0xffffffff);
        } catch { Dispose(); throw; }
        finally {
            if(pi.thread!=IntPtr.Zero) CloseHandle(pi.thread);
            if(initialized) DeleteProcThreadAttributeList(attributes);
            if(attributes!=IntPtr.Zero) Marshal.FreeHGlobal(attributes);
            if(value!=IntPtr.Zero) Marshal.FreeHGlobal(value);
        }
    }
    public static Tuple<System.Diagnostics.Process,Microsoft.Win32.SafeHandles.SafeProcessHandle,long,string> StartOwned(
        string name, string executable, string arguments, string directory, string expectedImage) {
        string phase="worker_membership";
        ProcessInfo pi=new ProcessInfo();
        Microsoft.Win32.SafeHandles.SafeProcessHandle original=null;
        System.Diagnostics.Process managed=null;
        bool completed=false, childCreated=false;
        try {
            if(!Owns(name,GetCurrentProcess())) throw new InvalidOperationException("Creating worker is not in the private job");
            long before=DateTime.UtcNow.ToFileTimeUtc();
            phase="create_suspended";
            Startup start=new Startup(); start.cb=Marshal.SizeOf(typeof(Startup));
            // The verified worker's private job has no breakaway flags. Membership
            // is inherited atomically at creation; CREATE_BREAKAWAY_FROM_JOB is absent.
            childCreated=CreateProcessBasic(executable,new StringBuilder("\""+executable+"\" "+arguments),IntPtr.Zero,IntPtr.Zero,false,4,IntPtr.Zero,directory,ref start,out pi);
            Check(childCreated);
            original=new Microsoft.Win32.SafeHandles.SafeProcessHandle(pi.process,true);
            phase="creation_identity";
            long created=Created(pi.process);
            if(created<before) throw new InvalidOperationException("Unexpected process creation identity");
            phase="private_job";
            if(!Owns(name,pi.process)) throw new InvalidOperationException("Created process is outside the private job");
            phase="image_query";
            string image=System.IO.Path.GetFullPath(Image(pi.process));
            phase="image_compare";
            if(!String.Equals(image,System.IO.Path.GetFullPath(expectedImage),StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Created process image differs from expected image");
            phase="managed_binding";
            // This is not discovery/adoption: only this CreateProcess result's PID is
            // bound while its original handle is pinned and its thread is suspended.
            managed=System.Diagnostics.Process.GetProcessById(unchecked((int)pi.id));
            IntPtr bound=managed.Handle;
            if(GetProcessId(bound)!=pi.id || Created(bound)!=created || !Owns(name,bound) ||
               !String.Equals(System.IO.Path.GetFullPath(Image(bound)),image,StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Managed handle does not match the creation-owned process");
            var launched=Tuple.Create(managed,original,created,image);
            phase="resume_verified";
            uint previousSuspendCount=ResumeThread(pi.thread);
            Check(previousSuspendCount!=0xffffffff);
            if(previousSuspendCount!=1) throw new InvalidOperationException("Unexpected created-thread suspend state");
            completed=true;
            return launched;
        } catch(Exception error) {
            if(!error.Data.Contains("acceptance_phase")) error.Data["acceptance_phase"]=phase;
            // Only the original creation-returned handle can be terminated here.
            // Preserve the setup exception even when cancellation already exited it.
            if(childCreated && pi.process!=IntPtr.Zero && WaitForSingleObject(pi.process,0)!=0) {
                TerminateProcess(pi.process,1);
                uint waited=WaitForSingleObject(pi.process,1000);
                if(waited!=0) error.Data["acceptance_cleanup_failed"]=true;
            }
            throw;
        } finally {
            if(childCreated && pi.thread!=IntPtr.Zero) CloseHandle(pi.thread);
            if(!completed) {
                try { if(managed!=null) managed.Dispose(); }
                finally {
                    if(original!=null) original.Dispose();
                    else if(childCreated && pi.process!=IntPtr.Zero) CloseHandle(pi.process);
                }
            }
        }
    }
    public bool Wait(uint milliseconds) {
        uint result=WaitForSingleObject(process,milliseconds);
        if(result==0xffffffff) throw new Win32Exception(Marshal.GetLastWin32Error());
        return result==0;
    }
    public int ExitCode { get { uint code; Check(GetExitCodeProcess(process,out code),"exit_code"); return unchecked((int)code); } }
    public void Cancel() { if(job!=IntPtr.Zero) Check(TerminateJobObject(job,1)); }
    public void Dispose() {
        GC.SuppressFinalize(this);
        // Neither worker nor children inherit this handle; abrupt supervisor exit also closes it.
        if(job!=IntPtr.Zero) { CloseHandle(job); job=IntPtr.Zero; }
        if(process!=IntPtr.Zero) { CloseHandle(process); process=IntPtr.Zero; }
    }
    public static bool Owns(string name, IntPtr handle) {
        IntPtr owned=OpenJobObject(4,false,name); // QUERY only; never retain a child job handle
        if(owned==IntPtr.Zero) return false;
        try { bool result; Check(IsProcessInJob(handle,owned,out result),"job_membership"); return result; }
        finally { CloseHandle(owned); }
    }
    public static long Created(IntPtr handle) { long c,e,k,u; Check(GetProcessTimes(handle,out c,out e,out k,out u),"creation_time"); return c; }
    public static string Image(IntPtr handle) {
        StringBuilder path=new StringBuilder(32768); int size=path.Capacity;
        Check(QueryFullProcessImageName(handle,0,path,ref size),"image_query"); return path.ToString();
    }
    public static void StopOwned(string name, IntPtr handle) {
        if(!Owns(name,handle)) throw new InvalidOperationException("Process ownership was not proven");
        if(WaitForSingleObject(handle,0)==0) return;
        Check(TerminateProcess(handle,1));
    }
}
