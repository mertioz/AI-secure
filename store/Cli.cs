using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;

internal static class Cli
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr LoadLibraryEx(string name, IntPtr reserved, uint flags);

    [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
    private static extern IntPtr GetProcAddress(IntPtr library, string name);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate int PythonMain(int argc, IntPtr argv);

    private static int Main(string[] args)
    {
        string runtime = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "runtime");
        IntPtr python = LoadLibraryEx(Path.Combine(runtime, "python314.dll"), IntPtr.Zero, 0x100 | 0x1000);
        IntPtr entry = python == IntPtr.Zero ? IntPtr.Zero : GetProcAddress(python, "Py_Main");
        if (entry == IntPtr.Zero)
        {
            Console.Error.WriteLine("Impossible de charger le moteur embarqué d’AI Secure.");
            return 1;
        }
        var arguments = new List<string> { Path.Combine(runtime, "python.exe"), "-I", "-B", "-X", "utf8", "-m", "ai_secure" };
        arguments.AddRange(args);
        var strings = new IntPtr[arguments.Count + 1];
        var table = GCHandle.Alloc(strings, GCHandleType.Pinned);
        try
        {
            for (int i = 0; i < arguments.Count; i++) strings[i] = Marshal.StringToHGlobalUni(arguments[i]);
            var run = (PythonMain)Marshal.GetDelegateForFunctionPointer(entry, typeof(PythonMain));
            return run(arguments.Count, table.AddrOfPinnedObject());
        }
        finally
        {
            foreach (IntPtr value in strings) if (value != IntPtr.Zero) Marshal.FreeHGlobal(value);
            table.Free();
        }
    }
}
