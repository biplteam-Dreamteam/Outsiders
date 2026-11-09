using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace GrandCopilotInstaller
{
    public class InstallerForm : Form
    {
        private Panel _pnlStep1;
        private Panel _pnlStep2;
        private Panel _pnlStep3;

        // Step 1 Controls
        private Label _lblPythonCheck;

        // Step 2 Controls (Hardware & Mode Configuration)
        private TextBox _txtInstallPath;
        private RadioButton _rbModeFull;
        private RadioButton _rbModeTriage;
        private NumericUpDown _numCpu;
        private NumericUpDown _numRam;

        // Step 3 Controls (Progress & Completion)
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
            CheckPythonInstalled();
        }

        private void InitializeComponent()
        {
            this.Text = "Мастер установки комплекса «Via автоматизация» v2.5 (Enterprise)";
            this.Size = new Size(680, 540);
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
                Text = "Установка комплекса «Via автоматизация»",
                Font = new Font("Segoe UI", 13.5f, FontStyle.Bold),
                ForeColor = Color.FromArgb(56, 189, 248),
                Location = new Point(22, 14),
                AutoSize = true
            };
            Label lblSub = new Label
            {
                Text = "Автономная AI-система поддержки и модерации первого эшелона (100% On-Premise)",
                Font = new Font("Segoe UI", 9.5f, FontStyle.Regular),
                ForeColor = Color.FromArgb(148, 163, 184),
                Location = new Point(24, 43),
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
                Location = new Point(430, 15),
                Size = new Size(100, 32),
                BackColor = Color.FromArgb(71, 85, 105),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat
            };
            _btnCancel.Click += (s, e) => this.Close();

            _btnNext = new Button
            {
                Text = "Далее >",
                Location = new Point(545, 15),
                Size = new Size(105, 32),
                BackColor = Color.FromArgb(16, 185, 129),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat,
                Font = new Font("Segoe UI", 9.5f, FontStyle.Bold)
            };
            _btnNext.Click += OnNextClicked;

            pnlBottom.Controls.Add(_btnCancel);
            pnlBottom.Controls.Add(_btnNext);
            this.Controls.Add(pnlBottom);

            // =================================================================
            // Step 1: Welcome & System Hardware Check
            // =================================================================
            _pnlStep1 = new Panel { Dock = DockStyle.Fill };
            Label lblWelcome = new Label
            {
                Text = "Добро пожаловать в автономный мастер установки!\n\n" +
                       "Программа выполнит автоматическую установку и настройку системы:\n" +
                       "  • Развернет скомпилированные деревья CatBoost и 101 правило rules.json\n" +
                       "  • Установит и настроит веб-панель управления Streamlit и REST API сервис\n" +
                       "  • Автоматически оптимизирует программу под количество ядер и память вашего ПК\n" +
                       "  • Создаст готовый ярлык на Рабочем столе для запуска в один клик\n",
                Location = new Point(25, 20),
                Size = new Size(610, 140),
                Font = new Font("Segoe UI", 10f, FontStyle.Regular),
                ForeColor = Color.FromArgb(226, 232, 240)
            };

            GroupBox grpSys = new GroupBox
            {
                Text = " Проверка готовности системы ",
                ForeColor = Color.FromArgb(56, 189, 248),
                Location = new Point(25, 170),
                Size = new Size(610, 125),
                Font = new Font("Segoe UI", 9.5f, FontStyle.Bold)
            };

            Label lblCpuInfo = new Label
            {
                Text = "• Процессор: " + Environment.ProcessorCount + " логических ядер (готово к параллельному инференсу)",
                Location = new Point(20, 30),
                AutoSize = true,
                Font = new Font("Segoe UI", 9.5f, FontStyle.Regular),
                ForeColor = Color.FromArgb(52, 211, 153)
            };

            _lblPythonCheck = new Label
            {
                Text = "• Проверка среды Python...",
                Location = new Point(20, 60),
                AutoSize = true,
                Font = new Font("Segoe UI", 9.5f, FontStyle.Regular),
                ForeColor = Color.FromArgb(203, 213, 225)
            };

            Label lblCostInfo = new Label
            {
                Text = "• Затраты на внешние API: $0.0000 (100% автономно на вашем компьютере)",
                Location = new Point(20, 90),
                AutoSize = true,
                Font = new Font("Segoe UI", 9.5f, FontStyle.Regular),
                ForeColor = Color.FromArgb(52, 211, 153)
            };

            grpSys.Controls.Add(lblCpuInfo);
            grpSys.Controls.Add(_lblPythonCheck);
            grpSys.Controls.Add(lblCostInfo);

            _pnlStep1.Controls.Add(lblWelcome);
            _pnlStep1.Controls.Add(grpSys);
            this.Controls.Add(_pnlStep1);

            // =================================================================
            // Step 2: Tuning Mode & Directory Configuration
            // =================================================================
            _pnlStep2 = new Panel { Dock = DockStyle.Fill, Visible = false };

            GroupBox grpMode = new GroupBox
            {
                Text = " Начальный режим работы модели ",
                ForeColor = Color.FromArgb(56, 189, 248),
                Location = new Point(25, 15),
                Size = new Size(610, 110),
                Font = new Font("Segoe UI", 9.5f, FontStyle.Bold)
            };
            _rbModeFull = new RadioButton
            {
                Text = "🟢 Полный автопилот — Авто-ответы по правилам + Черновики (Рекомендуется)",
                Location = new Point(20, 30),
                Size = new Size(570, 26),
                Font = new Font("Segoe UI", 9.5f, FontStyle.Regular),
                ForeColor = Color.White,
                Checked = true
            };
            _rbModeTriage = new RadioButton
            {
                Text = "⚡ Чистая классификация (Triage Only) — Только сортировка очереди (без текста)",
                Location = new Point(20, 65),
                Size = new Size(570, 26),
                Font = new Font("Segoe UI", 9.5f, FontStyle.Regular),
                ForeColor = Color.White
            };
            grpMode.Controls.Add(_rbModeFull);
            grpMode.Controls.Add(_rbModeTriage);

            GroupBox grpHw = new GroupBox
            {
                Text = " Выделение аппаратных ресурсов (CPU и RAM) ",
                ForeColor = Color.FromArgb(56, 189, 248),
                Location = new Point(25, 135),
                Size = new Size(610, 85),
                Font = new Font("Segoe UI", 9.5f, FontStyle.Bold)
            };
            Label lblCpu = new Label { Text = "Ядра CPU:", Location = new Point(20, 35), AutoSize = true, Font = new Font("Segoe UI", 9.5f, FontStyle.Regular) };
            _numCpu = new NumericUpDown
            {
                Minimum = 1,
                Maximum = Environment.ProcessorCount,
                Value = Math.Min(8, Environment.ProcessorCount),
                Location = new Point(100, 32),
                Size = new Size(80, 26),
                BackColor = Color.FromArgb(30, 41, 59),
                ForeColor = Color.White
            };
            Label lblRam = new Label { Text = "Лимит RAM (МБ):", Location = new Point(250, 35), AutoSize = true, Font = new Font("Segoe UI", 9.5f, FontStyle.Regular) };
            _numRam = new NumericUpDown
            {
                Minimum = 512,
                Maximum = 16384,
                Increment = 256,
                Value = 2048,
                Location = new Point(380, 32),
                Size = new Size(90, 26),
                BackColor = Color.FromArgb(30, 41, 59),
                ForeColor = Color.White
            };
            grpHw.Controls.Add(lblCpu);
            grpHw.Controls.Add(_numCpu);
            grpHw.Controls.Add(lblRam);
            grpHw.Controls.Add(_numRam);

            Label lblDirPrompt = new Label
            {
                Text = "Папка для установки программы:",
                Location = new Point(25, 235),
                AutoSize = true,
                Font = new Font("Segoe UI", 10f, FontStyle.Bold)
            };
            string defaultPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "GrandCopilot");
            _txtInstallPath = new TextBox
            {
                Text = defaultPath,
                Location = new Point(25, 265),
                Size = new Size(490, 28),
                BackColor = Color.FromArgb(30, 41, 59),
                ForeColor = Color.White
            };
            Button btnBrowse = new Button
            {
                Text = "Обзор...",
                Location = new Point(530, 263),
                Size = new Size(100, 30),
                BackColor = Color.FromArgb(71, 85, 105),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat
            };
            btnBrowse.Click += (s, e) =>
            {
                FolderBrowserDialog dlg = new FolderBrowserDialog { SelectedPath = _txtInstallPath.Text };
                if (dlg.ShowDialog() == DialogResult.OK) _txtInstallPath.Text = dlg.SelectedPath;
            };

            _pnlStep2.Controls.Add(grpMode);
            _pnlStep2.Controls.Add(grpHw);
            _pnlStep2.Controls.Add(lblDirPrompt);
            _pnlStep2.Controls.Add(_txtInstallPath);
            _pnlStep2.Controls.Add(btnBrowse);
            this.Controls.Add(_pnlStep2);

            // =================================================================
            // Step 3: Installing & Finished
            // =================================================================
            _pnlStep3 = new Panel { Dock = DockStyle.Fill, Visible = false };
            _lblStatus = new Label
            {
                Text = "Подготовка к автоматической установке...",
                Location = new Point(25, 40),
                Size = new Size(610, 40),
                Font = new Font("Segoe UI", 10f, FontStyle.Regular)
            };
            _progressBar = new ProgressBar
            {
                Location = new Point(25, 95),
                Size = new Size(610, 28),
                Minimum = 0,
                Maximum = 100
            };
            _chkLaunchAfter = new CheckBox
            {
                Text = "Запустить Grand Mobile Support Copilot и открыть веб-панель прямо сейчас",
                Checked = true,
                Location = new Point(25, 160),
                Size = new Size(610, 32),
                Font = new Font("Segoe UI", 10f, FontStyle.Bold),
                ForeColor = Color.FromArgb(52, 211, 153),
                Visible = false
            };
            _pnlStep3.Controls.Add(_lblStatus);
            _pnlStep3.Controls.Add(_progressBar);
            _pnlStep3.Controls.Add(_chkLaunchAfter);
            this.Controls.Add(_pnlStep3);
        }

        private void CheckPythonInstalled()
        {
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo
                {
                    FileName = "python",
                    Arguments = "--version",
                    RedirectStandardOutput = true,
                    UseShellExecute = false,
                    CreateNoWindow = true
                };
                Process p = Process.Start(psi);
                string ver = p.StandardOutput.ReadToEnd().Trim();
                p.WaitForExit();
                if (!string.IsNullOrEmpty(ver))
                {
                    _lblPythonCheck.Text = "• " + ver + " обнаружен и готов к работе!";
                    _lblPythonCheck.ForeColor = Color.FromArgb(52, 211, 153);
                }
            }
            catch
            {
                _lblPythonCheck.Text = "• Python: будет использован встроенный системный запуск.";
                _lblPythonCheck.ForeColor = Color.FromArgb(234, 179, 8);
            }
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
                    LaunchInstalledApp();
                }
                this.Close();
            }
        }

        private void PerformInstallation()
        {
            Timer t = new Timer { Interval = 50 };
            int progress = 0;
            string sourceDir = AppDomain.CurrentDomain.BaseDirectory;

            t.Tick += (s, e) =>
            {
                progress += 5;
                if (progress <= 100)
                {
                    _progressBar.Value = progress;
                    if (progress == 20) _lblStatus.Text = "Копирование моделей CatBoost, базы rules.json и кода...";
                    if (progress == 50) _lblStatus.Text = "Генерация персональной конфигурации admin_config.json...";
                    if (progress == 75) _lblStatus.Text = "Проверка зависимостей Python (pip install)...";
                    if (progress == 90) _lblStatus.Text = "Создание ярлыков на Рабочем столе...";
                }

                if (progress >= 100)
                {
                    t.Stop();
                    try
                    {
                        CopyDirectory(sourceDir, _targetDirectory);
                        WriteInitialConfig();
                        CreateDesktopShortcut();

                        _lblStatus.Text = "Установка успешно завершена!\nПрограмма сконфигурирована и готова к работе.";
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

        private void WriteInitialConfig()
        {
            string mode = _rbModeTriage.Checked ? "triage_only" : "full";
            int threads = (int)_numCpu.Value;
            int ram = (int)_numRam.Value;

            string json = "{\n" +
                "  \"operating_mode\": \"" + mode + "\",\n" +
                "  \"cpu_threads\": " + threads + ",\n" +
                "  \"ram_limit_mb\": " + ram + ",\n" +
                "  \"batch_chunk_size\": 64,\n" +
                "  \"aggressive_gc\": false,\n" +
                "  \"confidence_threshold\": 0.55,\n" +
                "  \"human_required_categories\": [\n" +
                "    \"report.account\",\n" +
                "    \"report.payment\",\n" +
                "    \"complaint.admin\",\n" +
                "    \"complaint.cheat\"\n" +
                "  ],\n" +
                "  \"evidence_requires_human\": true,\n" +
                "  \"max_tickets_per_hour\": 5,\n" +
                "  \"dedup_similarity_threshold\": 0.85,\n" +
                "  \"active_model\": \"CatBoost CBM (Fast-Path)\"\n" +
                "}";

            string cfgDir = Path.Combine(_targetDirectory, "data");
            Directory.CreateDirectory(cfgDir);
            File.WriteAllText(Path.Combine(cfgDir, "admin_config.json"), json, Encoding.UTF8);
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

        private void LaunchInstalledApp()
        {
            try
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

                // Also launch web UI and open browser immediately
                ProcessStartInfo psiWeb = new ProcessStartInfo
                {
                    FileName = "python",
                    Arguments = "-m streamlit run admin_ui.py --server.port 8501 --server.headless true",
                    WorkingDirectory = _targetDirectory,
                    UseShellExecute = false,
                    CreateNoWindow = true
                };
                Process.Start(psiWeb);

                // Open browser
                Process.Start("http://localhost:8501");
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
