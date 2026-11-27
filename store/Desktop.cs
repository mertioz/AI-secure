using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal sealed class Mission : IDisposable
{
    internal static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 1048576 };
    private readonly Process moteur;

    internal Mission(string politique)
    {
        string arguments = "--hote";
        // Un nom de fichier Windows ne contient pas de guillemets. Le chemin sélectionné désigne un fichier.
        if (politique != null) arguments += " --mission \"" + Path.GetFullPath(politique) + "\"";
        var depart = new ProcessStartInfo(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "AISecureCli.exe"), arguments) {
            WorkingDirectory = Path.GetTempPath(), UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
        };
        moteur = Process.Start(depart);
        moteur.BeginErrorReadLine();
    }

    internal async Task<Dictionary<string, object>> Envoyer(string texte)
    {
        var evenement = Json.DeserializeObject(texte) as Dictionary<string, object>;
        if (evenement == null) throw new ArgumentException("Saisissez un objet JSON pour l’événement.");
        // Le moteur reçoit les clés originales, y compris un éventuel doublon à refuser.
        bool chaine = false, echappe = false;
        var ligneJson = new StringBuilder(texte.Length + 1);
        foreach (char c in texte)
        {
            if (c == '\r' || c == '\n')
            {
                if (chaine) throw new ArgumentException("Échappez les retours à la ligne à l’intérieur des chaînes JSON.");
                ligneJson.Append(' ');
                continue;
            }
            if (c == '"' && !echappe) chaine = !chaine;
            echappe = chaine && c == '\\' && !echappe;
            ligneJson.Append(c);
        }
        byte[] octets = Encoding.UTF8.GetBytes(ligneJson.Append('\n').ToString());
        if (octets.Length > 1048576) throw new ArgumentException("L’événement dépasse 1 Mio.");
        Stream entree = moteur.StandardInput.BaseStream;
        await entree.WriteAsync(octets, 0, octets.Length);
        await entree.FlushAsync();
        Task<string> lecture = moteur.StandardOutput.ReadLineAsync();
        if (await Task.WhenAny(lecture, Task.Delay(8000)) != lecture)
        {
            Dispose();
            throw new IOException("Le moteur a dépassé le délai de réponse. Ouvrez une nouvelle mission.");
        }
        string ligne = await lecture;
        if (ligne == null) throw new IOException("Le moteur a terminé la session. Vérifiez la politique de notes choisie.");
        var reponse = Json.DeserializeObject(ligne) as Dictionary<string, object>;
        if (reponse == null) throw new IOException("La décision du moteur est illisible.");
        return reponse;
    }

    private bool ferme;
    public void Dispose()
    {
        if (ferme) return;
        ferme = true;
        try
        {
            moteur.StandardInput.Close();
            if (!moteur.WaitForExit(1200)) { moteur.Kill(); moteur.WaitForExit(1200); }
        }
        catch (IOException) { }
        catch (InvalidOperationException) { }
        finally { moteur.Dispose(); }
    }
}

internal sealed class Atelier : Form
{
    private static readonly Color Fond = Color.FromArgb(239, 244, 246), Encre = Color.FromArgb(19, 41, 57);
    private static readonly Color Secondaire = Color.FromArgb(66, 86, 99), Accent = Color.FromArgb(0, 105, 92);
    private static readonly Color Refus = Color.FromArgb(150, 58, 46);
    private const string Rapport = "{\"type\":\"rapport\"}";
    private static readonly string[] Noms = { "Écrire la note de mission", "Relire la note", "Tester une autre cible", "Envoyer un fragment", "Consulter le rapport" };
    private static readonly string[] Exemples = {
        "{\r\n  \"type\": \"appel\",\r\n  \"proposition\": {\r\n    \"action\": \"ecrire_note\",\r\n    \"parametres\": {\r\n      \"note\": \"mission\",\r\n      \"texte\": \"Le compte rendu est prêt.\"\r\n    }\r\n  }\r\n}",
        "{\r\n  \"type\": \"appel\",\r\n  \"proposition\": {\r\n    \"action\": \"lire_note\",\r\n    \"parametres\": {\"note\": \"mission\"}\r\n  }\r\n}",
        "{\r\n  \"type\": \"appel\",\r\n  \"proposition\": {\r\n    \"action\": \"ecrire_note\",\r\n    \"parametres\": {\r\n      \"note\": \"autre\",\r\n      \"texte\": \"Mise à jour de contrôle.\"\r\n    }\r\n  }\r\n}",
        "{\r\n  \"type\": \"fragment\",\r\n  \"canal\": \"donnees\",\r\n  \"texte\": \"Le relevé est disponible.\",\r\n  \"nouveau\": true\r\n}",
        Rapport
    };
    private readonly ComboBox exemples = new ComboBox();
    private readonly TextBox entree = new TextBox(), resultat = new TextBox();
    private readonly Label verdict = new Label(), politique = new Label();
    private readonly ListView journal = new ListView();
    private readonly List<Control> actions = new List<Control>();
    private Mission mission;
    private string cheminPolitique;
    private bool occupe;

    private static Label Texte(string texte, float taille, bool gras, Color couleur)
    {
        return new Label { Text = texte, ForeColor = couleur, Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleLeft, AutoEllipsis = true,
            Font = new Font(SystemFonts.MessageBoxFont.FontFamily, taille, gras ? FontStyle.Bold : FontStyle.Regular) };
    }

    private Button Bouton(string nom, bool primaire, Func<Task> action)
    {
        var bouton = new Button { Text = nom, AutoSize = true, Height = 38, FlatStyle = FlatStyle.Flat,
            BackColor = primaire ? Accent : Color.White, ForeColor = primaire ? Color.White : Encre,
            Padding = new Padding(10, 3, 10, 3), Margin = new Padding(0, 2, 9, 2), Cursor = Cursors.Hand };
        bouton.FlatAppearance.BorderColor = primaire ? Accent : Color.FromArgb(183, 197, 203);
        bouton.Click += async delegate { await Faire(action); };
        actions.Add(bouton);
        return bouton;
    }

    private static TableLayoutPanel Grille(int colonnes, int lignes)
    {
        return new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = colonnes, RowCount = lignes,
            Margin = Padding.Empty, Padding = Padding.Empty, GrowStyle = TableLayoutPanelGrowStyle.FixedSize };
    }

    internal Atelier()
    {
        Text = "AI Secure"; BackColor = Fond; AutoScaleMode = AutoScaleMode.Dpi;
        Font = new Font(SystemFonts.MessageBoxFont.FontFamily, 10); StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(1120, 720); MinimumSize = new Size(870, 650);
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        var page = Grille(1, 3);
        page.RowStyles.Add(new RowStyle(SizeType.Absolute, 86)); page.RowStyles.Add(new RowStyle(SizeType.Absolute, 58));
        page.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); Controls.Add(page);

        var entete = Grille(3, 1); entete.BackColor = Encre; entete.Padding = new Padding(27, 9, 21, 9);
        entete.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        entete.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 58)); entete.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        entete.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize)); page.Controls.Add(entete, 0, 0);
        var marque = new PictureBox { SizeMode = PictureBoxSizeMode.Zoom, Dock = DockStyle.Fill, Margin = new Padding(0, 5, 9, 5) };
        marque.Image = Image.FromFile(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Assets", "Square150.png"));
        entete.Controls.Add(marque, 0, 0);
        entete.Controls.Add(Texte("AI Secure", 21, true, Color.White), 1, 0);
        var nouvelle = Bouton("Nouvelle mission", false, () => Demarrer(cheminPolitique));
        nouvelle.Anchor = AnchorStyles.Right; entete.Controls.Add(nouvelle, 2, 0);

        var barre = Grille(2, 1); barre.BackColor = Color.White; barre.Padding = new Padding(28, 6, 20, 6);
        barre.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); barre.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        politique.Dock = DockStyle.Fill; politique.TextAlign = ContentAlignment.MiddleLeft; politique.ForeColor = Secondaire; politique.AutoEllipsis = true;
        barre.Controls.Add(politique, 0, 0);
        var commandes = new FlowLayoutPanel { AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, Anchor = AnchorStyles.Right, WrapContents = false };
        commandes.Controls.Add(Bouton("Charger une politique…", false, Charger));
        commandes.Controls.Add(Bouton("Confidentialité", false, Confidentialite));
        commandes.Controls.Add(Bouton("Guide d’intégration", false, Guide)); barre.Controls.Add(commandes, 1, 0); page.Controls.Add(barre, 0, 1);

        var corps = Grille(2, 2); corps.Padding = new Padding(20, 18, 20, 18);
        corps.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 55)); corps.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 45));
        corps.RowStyles.Add(new RowStyle(SizeType.Percent, 65)); corps.RowStyles.Add(new RowStyle(SizeType.Percent, 35)); page.Controls.Add(corps, 0, 2);
        var gauche = Grille(1, 4); gauche.BackColor = Color.White; gauche.Padding = new Padding(16, 10, 16, 12); gauche.Margin = new Padding(0, 0, 7, 12);
        gauche.RowStyles.Add(new RowStyle(SizeType.Absolute, 40)); gauche.RowStyles.Add(new RowStyle(SizeType.Absolute, 39));
        gauche.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); gauche.RowStyles.Add(new RowStyle(SizeType.Absolute, 49));
        gauche.Controls.Add(Texte("Événement de l’hôte", 15, true, Encre), 0, 0);
        exemples.DropDownStyle = ComboBoxStyle.DropDownList; exemples.Dock = DockStyle.Fill; exemples.AccessibleName = "Exemple d’événement";
        exemples.Items.AddRange(Noms); exemples.SelectedIndexChanged += delegate { entree.Text = Exemples[exemples.SelectedIndex]; };
        gauche.Controls.Add(exemples, 0, 1);
        Editeur(entree, false); entree.AccessibleName = "Événement JSON à examiner"; gauche.Controls.Add(entree, 0, 2);
        var soumettre = Bouton("Évaluer l’événement", true, () => Evaluer()); soumettre.Anchor = AnchorStyles.Left | AnchorStyles.Bottom;
        gauche.Controls.Add(soumettre, 0, 3); corps.Controls.Add(gauche, 0, 0);
        var droite = Grille(1, 3); droite.BackColor = Color.White; droite.Padding = new Padding(16, 10, 16, 16); droite.Margin = new Padding(7, 0, 0, 12);
        droite.RowStyles.Add(new RowStyle(SizeType.Absolute, 40)); droite.RowStyles.Add(new RowStyle(SizeType.Absolute, 48)); droite.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        droite.Controls.Add(Texte("Décision de la garde", 15, true, Encre), 0, 0);
        verdict.Dock = DockStyle.Fill; verdict.Font = new Font(Font.FontFamily, 16, FontStyle.Bold); verdict.TextAlign = ContentAlignment.MiddleLeft;
        droite.Controls.Add(verdict, 0, 1); Editeur(resultat, true); resultat.AccessibleName = "Réponse JSON"; droite.Controls.Add(resultat, 0, 2);
        corps.Controls.Add(droite, 1, 0);
        var historique = Grille(1, 2); historique.BackColor = Color.White; historique.Padding = new Padding(16, 4, 16, 12);
        historique.RowStyles.Add(new RowStyle(SizeType.Absolute, 48)); historique.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        var teteJournal = Grille(2, 1); teteJournal.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); teteJournal.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        teteJournal.Controls.Add(Texte("Journal de mission", 15, true, Encre), 0, 0);
        var exporter = Bouton("Exporter le rapport…", false, Exporter); exporter.Anchor = AnchorStyles.Right; teteJournal.Controls.Add(exporter, 1, 0);
        historique.Controls.Add(teteJournal, 0, 0);
        journal.View = View.Details; journal.Dock = DockStyle.Fill; journal.FullRowSelect = true; journal.BorderStyle = BorderStyle.FixedSingle;
        journal.Columns.Add("Heure", 110); journal.Columns.Add("Événement", 205); journal.Columns.Add("Décision", 145); journal.Columns.Add("Motif", 330);
        historique.Controls.Add(journal, 0, 1); corps.Controls.Add(historique, 0, 1); corps.SetColumnSpan(historique, 2);
        exemples.SelectedIndex = 0;
        FormClosed += delegate { if (mission != null) mission.Dispose(); marque.Image.Dispose(); };
    }

    private static void Editeur(TextBox champ, bool lecture)
    {
        champ.Multiline = true; champ.WordWrap = false; champ.ScrollBars = ScrollBars.Both; champ.Dock = DockStyle.Fill;
        champ.ReadOnly = lecture; champ.AcceptsReturn = true; champ.MaxLength = 65536; champ.BorderStyle = BorderStyle.FixedSingle;
        champ.Font = new Font("Consolas", 10.5f); champ.BackColor = lecture ? Color.FromArgb(243, 248, 247) : Color.FromArgb(23, 46, 59);
        champ.ForeColor = lecture ? Encre : Color.FromArgb(231, 241, 243);
    }

    internal async Task Faire(Func<Task> action)
    {
        if (occupe) return;
        occupe = true; foreach (var bouton in actions) bouton.Enabled = false;
        try { await action(); }
        catch (Exception erreur) { verdict.Text = "Erreur"; verdict.ForeColor = Refus; resultat.Text = erreur.Message; }
        finally { occupe = false; if (!IsDisposed) foreach (var bouton in actions) bouton.Enabled = true; }
    }

    internal async Task Demarrer(string fichier)
    {
        var candidate = new Mission(fichier);
        try { if (!(await candidate.Envoyer(Rapport)).ContainsKey("mission")) throw new IOException("Politique de notes incompatible."); }
        catch { candidate.Dispose(); throw; }
        if (mission != null) mission.Dispose(); mission = candidate; cheminPolitique = fichier;
        journal.Items.Clear(); verdict.Text = "Mission active"; verdict.ForeColor = Accent;
        resultat.Text = "Choisissez un événement ou saisissez son JSON, puis évaluez-le.";
        politique.Text = fichier == null ? "Politique de notes intégrée  ·  Stockage en mémoire" : "Politique chargée  ·  " + Path.GetFileName(fichier);
    }

    private async Task Charger()
    {
        using (var choix = new OpenFileDialog { Title = "Charger une politique de notes", Filter = "Politique JSON (*.json)|*.json", CheckFileExists = true })
            if (choix.ShowDialog(this) == DialogResult.OK) await Demarrer(choix.FileName);
    }

    private Task Guide()
    {
        Process.Start(new ProcessStartInfo("https://github.com/mertioz/AI-secure#brancher-un-agent") { UseShellExecute = true });
        return Task.FromResult(true);
    }

    private Task Confidentialite()
    {
        MessageBox.Show(this, File.ReadAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "PRIVACY.md"), Encoding.UTF8),
            "Confidentialité d’AI Secure", MessageBoxButtons.OK, MessageBoxIcon.Information);
        return Task.FromResult(true);
    }

    private async Task Exporter()
    {
        if (mission == null) throw new InvalidOperationException("Ouvrez une mission.");
        using (var choix = new SaveFileDialog { Title = "Exporter le rapport", Filter = "Rapport JSON (*.json)|*.json", FileName = "rapport-ai-secure.json" })
            if (choix.ShowDialog(this) == DialogResult.OK)
                File.WriteAllText(choix.FileName, Mission.Json.Serialize(await mission.Envoyer(Rapport)), new UTF8Encoding(false));
    }

    private static string Valeur(Dictionary<string, object> objet, string cle)
    {
        object valeur; return objet.TryGetValue(cle, out valeur) ? Convert.ToString(valeur) : "";
    }

    internal async Task<string> Evaluer()
    {
        if (mission == null) throw new InvalidOperationException("Ouvrez une mission.");
        var objet = Mission.Json.DeserializeObject(entree.Text) as Dictionary<string, object>;
        if (objet == null) throw new ArgumentException("Saisissez un objet JSON.");
        var reponse = await mission.Envoyer(entree.Text);
        string statut = Valeur(reponse, "statut"); string motif = Valeur(reponse, "motif");
        string nom = Valeur(objet, "type"); object proposition;
        if (objet.TryGetValue("proposition", out proposition) && proposition is Dictionary<string, object>)
            nom = Valeur((Dictionary<string, object>)proposition, "action");
        var traduction = new Dictionary<string, string> { {"autorisee", "Autorisée"}, {"bloquee", "Bloquée"}, {"active", "Active"}, {"terminee", "Terminée"}, {"suspendue", "Suspendue"}, {"programmee", "Programmée"}, {"erreur", "Erreur"} };
        string titre; if (!traduction.TryGetValue(statut, out titre)) titre = nom == "rapport" ? "Rapport" : statut;
        verdict.Text = titre; verdict.ForeColor = (statut == "bloquee" || statut == "erreur" || statut == "suspendue") ? Refus : Accent;
        var lignes = new List<string>(); foreach (var champ in reponse) lignes.Add("  " + Mission.Json.Serialize(champ.Key) + ": " + Mission.Json.Serialize(champ.Value));
        resultat.Text = "{\r\n" + string.Join(",\r\n", lignes) + "\r\n}";
        journal.Items.Insert(0, new ListViewItem(new [] {DateTime.Now.ToString("HH:mm:ss"), nom, titre, motif.Replace('_', ' ')}));
        return statut;
    }

    internal async Task Capturer(string dossier)
    {
        Directory.CreateDirectory(dossier);
        exemples.SelectedIndex = 0;
        if (await Evaluer() != "autorisee") throw new InvalidOperationException("Écriture du test refusée.");
        exemples.SelectedIndex = 1;
        if (await Evaluer() != "autorisee" || !resultat.Text.Contains("compte rendu")) throw new InvalidOperationException("Échec de la relecture.");
        ImageClient(Path.Combine(dossier, "atelier-lecture.png"));
        exemples.SelectedIndex = 2;
        if (await Evaluer() != "bloquee" || !resultat.Text.Contains("hors_mission")) throw new InvalidOperationException("Cible hors mission acceptée.");
        ImageClient(Path.Combine(dossier, "atelier-refus.png"));
        var doublon = await mission.Envoyer("{\"type\":\"fin\",\"type\":\"rapport\"}");
        if (Valeur(doublon, "motif") != "format_invalide") throw new InvalidOperationException("Événement ambigu accepté.");
    }

    private void ImageClient(string fichier)
    {
        Control contenu = Controls[0]; contenu.Refresh();
        using (var image = new Bitmap(contenu.Width, contenu.Height))
        {
            contenu.DrawToBitmap(image, new Rectangle(Point.Empty, image.Size)); image.Save(fichier, ImageFormat.Png);
        }
    }
}

internal static class Desktop
{
    [STAThread]
    private static int Main(string[] args)
    {
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        using (var fenetre = new Atelier())
        {
            bool capture = args.Length == 2 && args[0] == "--captures-store";
            int code = 0;
            if (capture)
            {
                fenetre.StartPosition = FormStartPosition.Manual; fenetre.Location = new Point(-24000, -24000);
                fenetre.ShowInTaskbar = false; fenetre.ClientSize = new Size(1440, 900);
            }
            fenetre.Shown += async delegate {
                if (!capture) { await fenetre.Faire(() => fenetre.Demarrer(null)); return; }
                try { await fenetre.Demarrer(null); await fenetre.Capturer(args[1]); }
                catch (Exception erreur) { Console.Error.WriteLine(erreur); code = 1; }
                finally { fenetre.Close(); }
            };
            Application.Run(fenetre);
            return code;
        }
    }
}
