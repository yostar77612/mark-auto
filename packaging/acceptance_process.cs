using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
public sealed class MarkAutoAcceptanceJob : IDisposable {
    IntPtr job, process;
    [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IShellLinkW {
        [PreserveSig] int GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int capacity, IntPtr findData, uint flags);
        [PreserveSig] int GetIDList(out IntPtr list);
        [PreserveSig] int SetIDList(IntPtr list);
        [PreserveSig] int GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder text, int capacity);
        [PreserveSig] int SetDescription([MarshalAs(UnmanagedType.LPWStr)] string text);
        [PreserveSig] int GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int capacity);
        [PreserveSig] int SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string path);
        [PreserveSig] int GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder arguments, int capacity);
        [PreserveSig] int SetArguments([MarshalAs(UnmanagedType.LPWStr)] string arguments);
        [PreserveSig] int GetHotkey(out short hotkey);
        [PreserveSig] int SetHotkey(short hotkey);
        [PreserveSig] int GetShowCmd(out int command);
        [PreserveSig] int SetShowCmd(int command);
        [PreserveSig] int GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int capacity, out int index);
        [PreserveSig] int SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string path, int index);
        [PreserveSig] int SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string path, uint reserved);
        [PreserveSig] int Resolve(IntPtr window, uint flags);
        [PreserveSig] int SetPath([MarshalAs(UnmanagedType.LPWStr)] string path);
    }
    public static MarkAutoShortcutMetadata ReadShortcutExact(string path) {
        // Load the ORIGINAL Unicode pathname. WScript.Shell.CreateShortcut uses
        // the ANSI code page and can silently return a new, empty shortcut view.
        if(String.IsNullOrWhiteSpace(path) || path.Length<3 || !Char.IsLetter(path[0]) ||
           path[1]!=':' || path[2]!='\\' || path.Substring(2).IndexOf(':')>=0)
            throw new ArgumentException("Ordinary absolute local shortcut path required");
        string full=System.IO.Path.GetFullPath(path);
        if(!String.Equals(full,path,StringComparison.Ordinal) ||
           !String.Equals(System.IO.Path.GetExtension(full),".lnk",StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException("Canonical original .lnk pathname required");
        for(string inspect=full; !String.IsNullOrEmpty(inspect); inspect=System.IO.Path.GetDirectoryName(inspect)) {
            uint attributes=PathAttributes(inspect);
            if(attributes==0xffffffff) throw new System.IO.FileNotFoundException("Original shortcut or ancestor missing",inspect);
            if((attributes & 0x400u)!=0) throw new InvalidOperationException("Shortcut reparse path refused");
        }
        using(var pinned=new System.IO.FileStream(full,System.IO.FileMode.Open,System.IO.FileAccess.Read,System.IO.FileShare.Read)) {
            if(pinned.Length==0 || pinned.Length>1048576) throw new InvalidOperationException("Shortcut metadata size refused");
            RequireSingleLinkDefaultStream(pinned.SafeFileHandle.DangerousGetHandle(),full);
            object instance=null;
            try {
                instance=Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("00021401-0000-0000-C000-000000000046")));
                var persist=(System.Runtime.InteropServices.ComTypes.IPersistFile)instance;
                persist.Load(full,0); // STGM_READ. Never Resolve, Save or invoke a verb.
                var link=(IShellLinkW)instance;
                var target=new StringBuilder(32768);
                var arguments=new StringBuilder(32768);
                var working=new StringBuilder(32768);
                Marshal.ThrowExceptionForHR(link.GetPath(target,target.Capacity,IntPtr.Zero,4)); // SLGP_RAWPATH
                Marshal.ThrowExceptionForHR(link.GetArguments(arguments,arguments.Capacity));
                Marshal.ThrowExceptionForHR(link.GetWorkingDirectory(working,working.Capacity));
                if(String.IsNullOrWhiteSpace(target.ToString()) || target.Length==target.Capacity-1 ||
                   arguments.Length==arguments.Capacity-1 || working.Length==working.Capacity-1)
                    throw new InvalidOperationException("Empty or truncated shortcut metadata refused");
                RequireSingleLinkDefaultStream(pinned.SafeFileHandle.DangerousGetHandle(),full);
                return new MarkAutoShortcutMetadata(target.ToString(),arguments.ToString(),working.ToString());
            } finally {
                // Both interfaces alias this one exclusively owned RCW.
                if(instance!=null && Marshal.IsComObject(instance)) Marshal.FinalReleaseComObject(instance);
            }
        }
    }
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

    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct StreamInfo {
        public long size;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=296)] public string name;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, EntryPoint="FindFirstStreamW", SetLastError=true)] static extern IntPtr FindFirstStream(string path, int level, out StreamInfo info, uint flags);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, EntryPoint="FindNextStreamW", SetLastError=true)] static extern bool FindNextStream(IntPtr search, out StreamInfo info);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool FindClose(IntPtr search);
    public static void RequireSingleLinkDefaultStream(IntPtr file, string path) {
        // Caller retains a read stream without write/delete sharing through hashing/copy.
        // Never infer alias safety from a pathname or from a failed metadata query.
        FileInfo before; Check(GetFileInformationByHandle(file,out before));
        if((before.attributes & (0x10u|0x400u))!=0 || before.links!=1)
            throw new InvalidOperationException("Regular single-link file required");
        StreamInfo stream;
        IntPtr search=FindFirstStream(path,0,out stream,0);
        if(search==new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error());
        try {
            if(!String.Equals(stream.name,"::$DATA",StringComparison.Ordinal))
                throw new InvalidOperationException("Only the default data stream is admitted");
            if(FindNextStream(search,out stream))
                throw new InvalidOperationException("Alternate data stream refused");
            int error=Marshal.GetLastWin32Error();
            if(error!=38) throw new Win32Exception(error); // ERROR_HANDLE_EOF only.
        } finally { FindClose(search); }
        FileInfo after; Check(GetFileInformationByHandle(file,out after));
        if(after.links!=1 || after.volume!=before.volume || after.indexHigh!=before.indexHigh ||
           after.indexLow!=before.indexLow || after.attributes!=before.attributes)
            throw new InvalidOperationException("File alias metadata changed");
    }


    public static void RequireNoDirectoryDataStreams(string path) {
        IntPtr file=CreateFile(path,0x80,1,IntPtr.Zero,3,0x02200000,IntPtr.Zero);
        if(file==new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error());
        try {
            FileInfo before; Check(GetFileInformationByHandle(file,out before));
            if((before.attributes & 0x10u)==0 || (before.attributes & 0x400u)!=0)
                throw new InvalidOperationException("Ordinary directory required");
            StreamInfo stream;
            IntPtr search=FindFirstStream(path,0,out stream,0);
            if(search!=new IntPtr(-1)) {
                try { throw new InvalidOperationException("Directory data stream refused"); }
                finally { FindClose(search); }
            }
            int error=Marshal.GetLastWin32Error();
            if(error!=38) throw new Win32Exception(error); // Only ERROR_HANDLE_EOF proves no $DATA streams.
            FileInfo after; Check(GetFileInformationByHandle(file,out after));
            if(after.volume!=before.volume || after.indexHigh!=before.indexHigh ||
               after.indexLow!=before.indexLow || after.attributes!=before.attributes)
                throw new InvalidOperationException("Directory metadata changed");
        } finally { CloseHandle(file); }
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
public sealed class MarkAutoShortcutMetadata {
    public string TargetPath { get; private set; }
    public string Arguments { get; private set; }
    public string WorkingDirectory { get; private set; }
    internal MarkAutoShortcutMetadata(string target,string arguments,string working) {
        TargetPath=target; Arguments=arguments; WorkingDirectory=working;
    }
}
// TEST ONLY: measure this process's exact fixture-file handles, not whether
// unrelated system readers exist. Never duplicate, adopt, close or mutate a
// snapshot handle; do not query the system-wide handle table or file contents.
public static class TestOnlyShortcutHandles {
    [StructLayout(LayoutKind.Sequential)] struct Entry {
        public IntPtr handle,handles,pointers;
        public uint access,type,attributes,reserved;
    }
    [DllImport("ntdll.dll")] static extern int NtQueryInformationProcess(IntPtr process,int information,IntPtr buffer,int length,out int returned);
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll",SetLastError=true)] static extern uint GetFileType(IntPtr file);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern uint GetFinalPathNameByHandle(IntPtr file,StringBuilder name,uint length,uint flags);
    [DllImport("kernel32.dll")] static extern void SetLastError(uint code);
    public static int CountExact(string canonicalOwnedFixturePath) {
        string path=canonicalOwnedFixturePath;
        if(String.IsNullOrEmpty(path) || path.Length<3 || !Char.IsLetter(path[0]) || path[1]!=':' || path[2]!='\\' ||
           path.Substring(2).IndexOf(':')>=0 || !String.Equals(System.IO.Path.GetFullPath(path),path,StringComparison.Ordinal))
            throw new ArgumentException("Canonical local owned-fixture pathname required");
        int size=65536,returned;
        IntPtr buffer=Marshal.AllocHGlobal(size);
        try {
            int status=NtQueryInformationProcess(GetCurrentProcess(),51,buffer,size,out returned);
            if(status==unchecked((int)0xC0000004) && returned>size && returned<=4194304) {
                Marshal.FreeHGlobal(buffer); buffer=IntPtr.Zero;
                size=returned; buffer=Marshal.AllocHGlobal(size);
                status=NtQueryInformationProcess(GetCurrentProcess(),51,buffer,size,out returned);
            }
            if(status!=0) throw new InvalidOperationException("Current-process handle query failed: "+status.ToString("X8"));
            int stride=Marshal.SizeOf(typeof(Entry)),header=IntPtr.Size*2;
            if(returned<header || returned>size) throw new InvalidOperationException("Current-process handle snapshot length refused");
            long count=IntPtr.Size==8 ? Marshal.ReadInt64(buffer) : Marshal.ReadInt32(buffer);
            if(count<0 || count>(returned-header)/stride) throw new InvalidOperationException("Current-process handle snapshot bounds refused");
            int matches=0;
            for(int index=0;index<count;index++) {
                var entry=(Entry)Marshal.PtrToStructure(IntPtr.Add(buffer,header+index*stride),typeof(Entry));
                SetLastError(0);
                uint type=GetFileType(entry.handle);
                if(type!=1) {
                    int error=Marshal.GetLastWin32Error();
                    // Non-file objects and already-closed snapshot entries are
                    // not live disk-file handles. Unknown query failures refuse.
                    if(type==0 && error!=0 && error!=6) throw new Win32Exception(error);
                    continue;
                }
                var name=new StringBuilder(32768);
                uint length=GetFinalPathNameByHandle(entry.handle,name,(uint)name.Capacity,0);
                if(length==0) throw new Win32Exception(Marshal.GetLastWin32Error());
                if(length>=name.Capacity) throw new InvalidOperationException("Current-process file name truncated");
                string actual=name.ToString();
                if(actual.StartsWith("\\\\?\\",StringComparison.Ordinal)) actual=actual.Substring(4);
                if(String.Equals(actual,path,StringComparison.OrdinalIgnoreCase)) matches++;
            }
            return matches;
        } finally { if(buffer!=IntPtr.Zero) Marshal.FreeHGlobal(buffer); }
    }
    public static void RequireClosed(string canonicalOwnedFixturePath) {
        if(CountExact(canonicalOwnedFixturePath)!=0)
            throw new InvalidOperationException("Current-process fixture file handle remains open");
    }
}
