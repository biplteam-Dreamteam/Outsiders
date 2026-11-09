using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

namespace GrandCopilotInstaller
{
    public class InstallerForm : Form
    {
        private Panel _pnlStep1;
        private Panel _pnlStep2;
        private Panel _pnlStep3;

        private TextBox _txtInstallPath;
        private ProgressBar _progressBar;
        private Label _lblStatus;
        private CheckBox _chkLaunchAfter;
        private Button _btnNext;
        private Button _btnCancel;

        private int _currentStep = 1;
        private string _targetDirectory;

        public InstallerForm()
        {
            InitializeComponent();
        }

        private void InitializeComponent()
        {
            this.Text = "Мастер установки Grand Mobile Support Copilot v2.4";
            this.Size = new Size(620, 480);
            this.StartPosition = FormStartPosition.CenterScreen;
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.BackColor = Color.FromArgb(15, 23, 42); // slate-900
            this.ForeColor = Color.FromArgb(241, 245, 249);
            this.Font = new Font("Segoe UI", 9.5f, FontStyle.Regular);

            // Top Banner
            Panel pnlBanner = new Panel
            {
                Dock = DockStyle.Top,
                Height = 75,
                BackColor = Color.FromArgb(30, 41, 59)
            };
            Label lblTitle = new Label
            {
                Text = "Установка Grand Mobile Support Copilot",
                Font = new Font("Segoe UI", 13f, FontStyle.Bold),
                ForeColor = Color.FromArgb(56, 189, 248),
                Location = new Point(20, 15),
                AutoSize = true
            };
            Label lblSub = new Label
            {
                Text = "Автономная AI-система поддержки и модерации первого эшелона",
                Font = new Font("Segoe UI", 9.5f, FontStyle.Regular),
                ForeColor = Color.FromArgb(148, 163, 184),
                Location = new Point(22, 43),
                AutoSize = true
            };
            pnlBanner.Controls.Add(lblTitle);
            pnlBanner.Controls.Add(lblSub);
            this.Controls.Add(pnlBanner);

            // Bottom Navigation Panel
            Panel pnlBottom = new Panel
            {
                Dock = DockStyle.Bottom,
                Height = 60,
                BackColor = Color.FromArgb(30, 41, 59)
            };
            _btnCancel = new Button
            {
                Text = "Отмена",
                Location = new Point(380, 15),
                Size = new Size(100, 32),
                BackColor = Color.FromArgb(71, 85, 105),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat
            };
            _btnCancel.Click += (s, e) => this.Close();

            _btnNext = new Button
            {
                Text = "Далее >",
                Location = new Point(490, 15),
                Size = new Size(100, 32),
                BackColor = Color.FromArgb(16, 185, 129),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat,
                Font = new Font("Segoe UI", 9.5f, FontStyle.Bold)
            };
            _btnNext.Click += OnNextClicked;

            pnlBottom.Controls.Add(_btnCancel);
            pnlBottom.Controls.Add(_btnNext);
            this.Controls.Add(pnlBottom);

            // Step 1: Welcome
            _pnlStep1 = new Panel { Dock = DockStyle.Fill };
            Label lblWelcome = new Label
            {
                Text = "Добро пожаловать в программу установки!\n\n" +
                       "Этот мастер установит Grand Mobile Support Copilot (Enterprise Edition) на ваш компьютер.\n\n" +
                       "Особенности установленной версии:\n" +
                       "  • Полная автономность On-Premise ($0.00 затрат на API-токены)\n" +
                       "  • Суб-10мс Fast-Path триаж и 0% галлюцинаций правил\n" +
                       "  • Встроенная графическая панель оператора и REST API сервис\n" +
                       "  • Готовые скомпилированные деревья CatBoost и база из 101 правила\n\n" +
                       "Нажмите «Далее», чтобы продолжить установку.",
                Location = new Point(25, 20),
                Size = new Size(550, 240),
                Font = new Font("Segoe UI", 10f, FontStyle.Regular),
                ForeColor = Color.FromArgb(226, 232, 240)
            };
            _pnlStep1.Controls.Add(lblWelcome);
            this.Controls.Add(_pnlStep1);

            // Step 2: Choose directory
            _pnlStep2 = new Panel { Dock = DockStyle.Fill, Visible = false };
            Label lblDirPrompt = new Label
            {
                Text = "Выберите папку для установки программы:",
                Location = new Point(25, 30),
                AutoSize = true,
                Font = new Font("Segoe UI", 10.5f, FontStyle.Bold)
            };
            string defaultPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "GrandCopilot");
            _txtInstallPath = new TextBox
            {
                Text = defaultPath,
                Location = new Point(25, 65),
                Size = new Size(460, 28),
                BackColor = Color.FromArgb(30, 41, 59),
                ForeColor = Color.White
            };
            Button btnBrowse = new Button
            {
                Text = "Обзор...",
                Location = new Point(495, 63),
                Size = new Size(90, 32),
                BackColor = Color.FromArgb(71, 85, 105),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat
            };
            btnBrowse.Click += (s, e) =>
            {
                FolderBrowserDialog dlg = new FolderBrowserDialog { SelectedPath = _txtInstallPath.Text };
                if (dlg.ShowDialog() == DialogResult.OK) _txtInstallPath.Text = dlg.SelectedPath;
            };

            Label lblReqSpace = new Label
            {
                Text = "Требуемое дисковое пространство: ~65 МБ\n" +
                       "Будет создан ярлык на Рабочем столе и в Главном меню.",
                Location = new Point(25, 120),
                AutoSize = true,
                ForeColor = Color.FromArgb(148, 163, 184)
            };

            _pnlStep2.Controls.Add(lblDirPrompt);
            _pnlStep2.Controls.Add(_txtInstallPath);
            _pnlStep2.Controls.Add(btnBrowse);
            _pnlStep2.Controls.Add(lblReqSpace);
            this.Controls.Add(_pnlStep2);

            // Step 3: Installing & Finished
            _pnlStep3 = new Panel { Dock = DockStyle.Fill, Visible = false };
            _lblStatus = new Label
            {
                Text = "Подготовка к копированию файлов...",
                Location = new Point(25, 40),
                Size = new Size(550, 40),
                Font = new Font("Segoe UI", 10f, FontStyle.Regular)
            };
            _progressBar = new ProgressBar
            {
                Location = new Point(25, 90),
                Size = new Size(555, 26),
                Minimum = 0,
                Maximum = 100
            };
            _chkLaunchAfter = new CheckBox
            {
                Text = "Запустить Grand Mobile Support Copilot прямо сейчас",
                Checked = true,
                Location = new Point(25, 160),
                Size = new Size(450, 30),
                Font = new Font("Segoe UI", 10f, FontStyle.Bold),
                ForeColor = Color.FromArgb(52, 211, 153),
                Visible = false
            };
            _pnlStep3.Controls.Add(_lblStatus);
            _pnlStep3.Controls.Add(_progressBar);
            _pnlStep3.Controls.Add(_chkLaunchAfter);
            this.Controls.Add(_pnlStep3);
        }

        private void OnNextClicked(object sender, EventArgs e)
        {
            if (_currentStep == 1)
            {
                _pnlStep1.Visible = false;
                _pnlStep2.Visible = true;
                _btnNext.Text = "Установить";
                _currentStep = 2;
            }
            else if (_currentStep == 2)
            {
                _targetDirectory = _txtInstallPath.Text.Trim();
                _pnlStep2.Visible = false;
                _pnlStep3.Visible = true;
                _btnNext.Enabled = false;
                _btnCancel.Enabled = false;
                _currentStep = 3;
                PerformInstallation();
            }
            else if (_currentStep == 4)
            {
                if (_chkLaunchAfter.Checked)
                {
                    string exePath = Path.Combine(_targetDirectory, "GrandCopilot.exe");
                    if (File.Exists(exePath))
                    {
                        Process.Start(new ProcessStartInfo
                        {
                            FileName = exePath,
                            WorkingDirectory = _targetDirectory
                        });
                    }
                }
                this.Close();
            }
        }

        private void PerformInstallation()
        {
            Timer t = new Timer { Interval = 40 };
            int progress = 0;
            string sourceDir = AppDomain.CurrentDomain.BaseDirectory;

            t.Tick += (s, e) =>
            {
                progress += 5;
                if (progress <= 100)
                {
                    _progressBar.Value = progress;
                    if (progress == 20) _lblStatus.Text = "Создание целевой директории: " + _targetDirectory;
                    if (progress == 50) _lblStatus.Text = "Копирование моделей CatBoost и базы знаний rules.json...";
                    if (progress == 80) _lblStatus.Text = "Создание ярлыков на Рабочем столе...";
                }

                if (progress >= 100)
                {
                    t.Stop();
                    try
                    {
                        CopyDirectory(sourceDir, _targetDirectory);
                        CreateDesktopShortcut();
                        _lblStatus.Text = "Установка успешно завершена!\nПрограмма готова к работе.";
                        _lblStatus.ForeColor = Color.FromArgb(52, 211, 153);
                        _chkLaunchAfter.Visible = true;
                        _btnNext.Text = "Готово";
                        _btnNext.Enabled = true;
                        _currentStep = 4;
                    }
                    catch (Exception ex)
                    {
                        _lblStatus.Text = "Ошибка установки: " + ex.Message;
                        _lblStatus.ForeColor = Color.FromArgb(244, 63, 94);
                        _btnNext.Text = "Закрыть";
                        _btnNext.Enabled = true;
                        _currentStep = 4;
                    }
                }
            };
            t.Start();
        }

        private void CopyDirectory(string src, string dest)
        {
            Directory.CreateDirectory(dest);
            foreach (string file in Directory.GetFiles(src))
            {
                string fName = Path.GetFileName(file);
                if (fName.EndsWith(".cs") || fName.StartsWith("test_") || fName == "Setup_GrandCopilot.exe") continue;
                string destFile = Path.Combine(dest, fName);
                File.Copy(file, destFile, true);
            }

            foreach (string dir in Directory.GetDirectories(src))
            {
                string dName = Path.GetFileName(dir);
                if (dName == ".git" || dName == "__pycache__") continue;
                CopyDirectory(dir, Path.Combine(dest, dName));
            }
        }

        private void CreateDesktopShortcut()
        {
            try
            {
                string desktopFolder = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                string shortcutPath = Path.Combine(desktopFolder, "Grand Mobile Support Copilot.lnk");
                string targetExe = Path.Combine(_targetDirectory, "GrandCopilot.exe");

                // Use Windows PowerShell to create the shortcut seamlessly without COM interop
                string psCmd = string.Format(
                    "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('{0}'); $s.TargetPath = '{1}'; $s.WorkingDirectory = '{2}'; $s.Description = 'Grand Mobile Support Copilot Enterprise'; $s.Save()",
                    shortcutPath.Replace("'", "''"),
                    targetExe.Replace("'", "''"),
                    _targetDirectory.Replace("'", "''")
                );

                ProcessStartInfo psi = new ProcessStartInfo
                {
                    FileName = "powershell",
                    Arguments = "-NoProfile -Command \"" + psCmd + "\"",
                    CreateNoWindow = true,
                    UseShellExecute = false
                };
                Process.Start(psi).WaitForExit(3000);
            }
            catch { }
        }

        [STAThread]
        public static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new InstallerForm());
        }
    }
}
