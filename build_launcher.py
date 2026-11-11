import os
import sys
import subprocess

dicta_dir = os.path.abspath(os.path.dirname(__file__))
cs_file = os.path.join(dicta_dir, "_launcher.cs")
exe_file = os.path.join(dicta_dir, "Dicta.exe")
ico_file = os.path.join(dicta_dir, "dicta.ico")

cs_source = """using System;
using System.IO;
using System.Diagnostics;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("Dicta")]
[assembly: AssemblyProduct("Dicta")]
[assembly: AssemblyDescription("Dicta - 音声文字起こし再生スタジオ")]
[assembly: AssemblyCompany("Dicta Open Source Project")]
[assembly: AssemblyCopyright("Copyright (C) 2026 Dicta Project & Antigravity")]
[assembly: AssemblyVersion("3.2.0.0")]
[assembly: AssemblyFileVersion("3.2.0.0")]

static class Program
{
    static string FindPythonw()
    {
        string baseDir = AppDomain.CurrentDomain.BaseDirectory;
        string localPyw = Path.Combine(baseDir, "pythonw.exe");
        if (File.Exists(localPyw)) return localPyw;

        string venvPyw = Path.Combine(baseDir, "venv", "Scripts", "pythonw.exe");
        if (File.Exists(venvPyw)) return venvPyw;

        string dotVenvPyw = Path.Combine(baseDir, ".venv", "Scripts", "pythonw.exe");
        if (File.Exists(dotVenvPyw)) return dotVenvPyw;

        string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (!string.IsNullOrEmpty(localAppData))
        {
            string pyRoot = Path.Combine(localAppData, "Programs", "Python");
            if (Directory.Exists(pyRoot))
            {
                try
                {
                    string[] dirs = Directory.GetDirectories(pyRoot, "Python3*");
                    Array.Sort(dirs);
                    Array.Reverse(dirs);
                    foreach (string d in dirs)
                    {
                        string candidate = Path.Combine(d, "pythonw.exe");
                        if (File.Exists(candidate)) return candidate;
                    }
                }
                catch {}
            }
        }

        string progFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        if (!string.IsNullOrEmpty(progFiles))
        {
            string[] dirs = Directory.GetDirectories(progFiles, "Python3*");
            Array.Sort(dirs);
            Array.Reverse(dirs);
            foreach (string d in dirs)
            {
                string candidate = Path.Combine(d, "pythonw.exe");
                if (File.Exists(candidate)) return candidate;
            }
        }

        return "pythonw.exe";
    }

    [STAThread]
    static void Main(string[] args)
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        string script = Path.Combine(dir, "dicta.py");

        string pyw = FindPythonw();

        string cmdArgs = "\\"" + script + "\\"";
        if (args != null && args.Length > 0)
        {
            foreach (string a in args)
            {
                cmdArgs += " \\"" + a + "\\"";
            }
        }

        ProcessStartInfo psi = new ProcessStartInfo();
        psi.FileName = pyw;
        psi.Arguments = cmdArgs;
        psi.WorkingDirectory = dir;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;

        try
        {
            Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show("Dictaの起動に失敗しました:\\n" + ex.Message, "Dicta エラー", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
"""

with open(cs_file, "w", encoding="utf-8") as f:
    f.write(cs_source)

csc_exe = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not os.path.exists(csc_exe):
    csc_exe = r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"

cmd = [
    csc_exe,
    "/nologo",
    "/target:winexe",
    "/optimize+",
    f"/out:{exe_file}",
    f"/win32icon:{ico_file}",
    "/r:System.Windows.Forms.dll",
    cs_file
]

try:
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    print("Dicta.exe compiled successfully with ZERO personal paths!")
    print(f"Path: {exe_file} ({os.path.getsize(exe_file)} bytes)")
except subprocess.CalledProcessError as e:
    print("Compilation failed:")
    print(e.stderr or e.stdout)
finally:
    if os.path.exists(cs_file):
        os.remove(cs_file)
