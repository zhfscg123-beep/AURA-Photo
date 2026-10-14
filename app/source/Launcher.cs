using System;
using System.IO;
using System.Diagnostics;
using System.Reflection;
using System.Windows.Forms;
[assembly: AssemblyTitle("AURA Photo")]
[assembly: AssemblyVersion("0.2.0.0")]
[assembly: AssemblyFileVersion("0.2.0.0")]
class Launcher {
 [STAThread] static int Main(string[] args) {
  string root=AppDomain.CurrentDomain.BaseDirectory;
  string python=Path.Combine(root,"runtime","pythonw.exe");
  string script=Path.Combine(root,"portable_bootstrap.py");
  try {
   if(!File.Exists(python)||!File.Exists(script)) throw new FileNotFoundException("AURA Photo files are missing. Reinstall or fully extract the package.\nAURA Photo 文件不完整，请重新安装或完整解压便携包。");
   string arguments=Quote(script);
   foreach(string arg in args) arguments+=" "+Quote(arg);
   ProcessStartInfo info=new ProcessStartInfo(python,arguments);
   info.WorkingDirectory=root;info.UseShellExecute=false;info.CreateNoWindow=true;
   info.EnvironmentVariables["PYTHONNOUSERSITE"]="1";
   Process child=Process.Start(info);
   if(Array.IndexOf(args,"--self-test")>=0) {child.WaitForExit();return child.ExitCode;}
   return 0;
  } catch(Exception e) { MessageBox.Show(e.Message,"AURA Photo",MessageBoxButtons.OK,MessageBoxIcon.Error);return 1; }
 }
 static string Quote(string text) {
  string value="\"";int slashes=0;
  foreach(char c in text) {
   if(c=='\\') {slashes++;continue;}
   if(c=='\"') value+=new string('\\',slashes*2+1)+c;
   else value+=new string('\\',slashes)+c;
   slashes=0;
  }
  return value+new string('\\',slashes*2)+"\"";
 }
}
