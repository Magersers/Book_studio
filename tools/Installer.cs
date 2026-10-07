using System;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Diagnostics;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;

// Small source-distribution bootstrapper. Model weights are downloaded by setup.ps1.
class Installer : Form {
    TextBox destination = new TextBox();
    TextBox output = new TextBox();
    Button install = new Button();
    ProgressBar progress = new ProgressBar();
    bool running;
    public Installer() {
        Text = "Book Studio — Setup"; Width = 780; Height = 560;
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(21,25,34); ForeColor = Color.White;
        Font = new Font("Segoe UI", 10);
        var title = new Label { Text = "Book Studio", Left = 24, Top = 20, Width = 700, Height = 40, Font = new Font("Segoe UI",22,FontStyle.Bold) };
        var info = new Label { Text = "Voice avatars and audiobooks • English / Русский\nSetup downloads Python, dependencies and AI models. NVIDIA GPU required.", Left=24,Top=68,Width=710,Height=55 };
        destination.SetBounds(24,132,710,30);
        destination.Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"BookStudio");
        output.SetBounds(24,180,710,265); output.Multiline=true; output.ScrollBars=ScrollBars.Vertical; output.ReadOnly=true;
        output.BackColor=Color.FromArgb(16,18,24);output.ForeColor=Color.Gainsboro;
        progress.SetBounds(24,458,520,24); progress.Style=ProgressBarStyle.Marquee; progress.Visible=false;
        install.SetBounds(554,455,180,34); install.Text="Install / Установить";install.BackColor=Color.FromArgb(105,79,166);
        install.Click += async (sender,e) => await RunInstall();
        Controls.AddRange(new Control[]{title,info,destination,output,progress,install});
        FormClosing += (sender,e) => { if(running) { e.Cancel=true;MessageBox.Show(this,"Please wait for setup to finish. Downloads can take several minutes.","Setup running"); } };
    }
    void Log(string text) { if(text!=null && IsHandleCreated) BeginInvoke(new Action(()=>output.AppendText(text+Environment.NewLine))); }
    static void Extract(string folder) {
        folder=Path.GetFullPath(folder);Directory.CreateDirectory(folder);
        string prefix=folder.TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;
        using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("BookStudio.Source.zip"))
        using(var archive=new ZipArchive(stream,ZipArchiveMode.Read)) {
            foreach(var entry in archive.Entries) {
                string target=Path.GetFullPath(Path.Combine(folder,entry.FullName));
                if(!target.StartsWith(prefix,StringComparison.OrdinalIgnoreCase))throw new InvalidDataException("Unsafe archive path");
                if(entry.FullName.EndsWith("/")){Directory.CreateDirectory(target);continue;}
                Directory.CreateDirectory(Path.GetDirectoryName(target));
                using(var input=entry.Open())using(var file=File.Create(target))input.CopyTo(file);
            }
        }
    }
    async Task RunInstall() {
        running=true;install.Enabled=false;destination.Enabled=false;progress.Visible=true;
        try {
            string folder=Path.GetFullPath(destination.Text);
            await Task.Run(()=>Extract(folder));
            Log("Source extracted. Installing; please wait...");
            var start=new ProcessStartInfo("powershell.exe","-NoProfile -ExecutionPolicy Bypass -File \""+Path.Combine(folder,"setup.ps1")+"\"");
            start.WorkingDirectory=folder;start.UseShellExecute=false;start.CreateNoWindow=true;start.WindowStyle=ProcessWindowStyle.Hidden;
            start.RedirectStandardOutput=true;start.RedirectStandardError=true;
            int result=await Task.Run(()=>{
                using(var process=new Process()){process.StartInfo=start;process.OutputDataReceived+=(s,e)=>Log(e.Data);process.ErrorDataReceived+=(s,e)=>Log(e.Data);
                    process.Start();process.BeginOutputReadLine();process.BeginErrorReadLine();process.WaitForExit();return process.ExitCode;}
            });
            if(result!=0)throw new Exception("Setup failed. See the log above. You can rerun setup.cmd in the installation folder.");
            Log("Ready. Launch Book Studio from the desktop shortcut.");
            MessageBox.Show(this,"Installation complete. Use the desktop shortcut to launch.\nУстановка завершена. Используйте ярлык на рабочем столе.","Book Studio");
        } catch(Exception ex){Log(ex.Message);MessageBox.Show(this,ex.Message,"Setup error");}
        finally{running=false;install.Enabled=true;destination.Enabled=true;progress.Visible=false;}
    }
    [STAThread] static int Main(string[] args) {
        // Build verification: only extract to an explicit empty directory; never install.
        if(args.Length==2 && args[0]=="--verify-extract") { if(Directory.Exists(args[1]))return 2;Extract(args[1]);return File.Exists(Path.Combine(args[1],"desktop_app.py"))?0:3; }
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);Application.Run(new Installer());return 0;
    }
}
